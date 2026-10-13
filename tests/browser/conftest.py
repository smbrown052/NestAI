"""Run regressions against migrated PostgreSQL, FastAPI and the deployed UI."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from uuid import uuid4

import pytest
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "services" / "api"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed and "page" in item.funcargs:
        report.sections.append(("Streamlit browser text", item.funcargs["page"].locator("body").inner_text()[:6000]))


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait(process, url, log):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"Runtime exited ({process.returncode}): {log.read_text()}")
        try:
            if requests.get(url, timeout=1).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.2)
    pytest.fail(f"Runtime not ready at {url}: {log.read_text()}")


@pytest.fixture(scope="session")
def runtime():
    database_url = os.getenv(
        "NESTAI_BROWSER_DATABASE_URL",
        "postgresql+psycopg2://runner@127.0.0.1:55432/nestai_browser",
    )
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql" or url.database != "nestai_browser":
        pytest.fail("Browser tests require an isolated PostgreSQL database named nestai_browser")
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        if not conn.execute(text("SELECT 1 FROM pg_database WHERE datname='nestai_browser'")).scalar():
            conn.execute(text("CREATE DATABASE nestai_browser"))
    admin.dispose()
    api_port, ui_port = _port(), _port()
    api_url, ui_url = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{ui_port}"
    env = os.environ.copy()
    # Never inherit production provider credentials in deterministic tests.
    for key in list(env):
        if key.startswith(("STRIPE_", "SMTP_", "SENDGRID_", "OPENAI_", "GOOGLE_", "WALKSCORE_")):
            env.pop(key)
    env.update(
        DATABASE_URL=database_url,
        ENVIRONMENT="test",
        JWT_SECRET_KEY=secrets.token_urlsafe(48),
        NESTAI_API_BASE_URL=api_url,
        NESTAI_STREAMLIT_URL=ui_url,
        NESTAI_PROVIDER_MODE="mock",
        NESTAI_OWNER_EMAIL="",
        PYTHONPATH=str(ROOT),
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API, env=env, check=True, capture_output=True, text=True,
    )
    processes, logs, handles = [], [], []
    try:
        for name, command, cwd, health in [
            ("api", [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(api_port)], API, api_url + "/health"),
            ("ui", [sys.executable, "-m", "streamlit", "run", str(ROOT / "legacy/streamlit/app.py"),
                    "--server.address=127.0.0.1", f"--server.port={ui_port}",
                    "--server.headless=true", "--server.fileWatcherType=none",
                    "--browser.gatherUsageStats=false"], ROOT, ui_url + "/_stcore/health"),
        ]:
            log = Path(__file__).parent / f".{name}-{uuid4().hex}.log"
            logs.append(log)
            handle = log.open("w")
            handles.append(handle)
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT)
            processes.append(process)
            _wait(process, health, log)
        yield {"api": api_url, "ui": ui_url, "database_url": database_url}
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        for handle in handles:
            handle.close()
        for log in logs:
            log.unlink(missing_ok=True)


@pytest.fixture
def account(runtime):
    """Privileged plans are seeded directly; public provisioning is never used."""
    from pwdlib import PasswordHash

    engine = create_engine(runtime["database_url"])
    def create(plan="free"):
        email = f"browser-{uuid4().hex}@example.com"
        password = secrets.token_urlsafe(20)
        with engine.begin() as conn:
            user_id = conn.execute(text("""
                INSERT INTO users
                (email, hashed_password, display_name, is_active, is_admin, tier,
                 active_plan, subscription_status, beta_tester, trial_used,
                 cancel_at_period_end, referral_credit_cents, referral_code, created_at, updated_at)
                VALUES (:email, :password, 'Browser Member', true, false, :plan,
                        :plan, 'active', false, false, false, 0, :referral, now(), now())
                RETURNING id
            """), {"email": email, "password": PasswordHash.recommended().hash(password),
                   "plan": plan, "referral": uuid4().hex}).scalar_one()
        response = requests.post(runtime["api"] + "/auth/login",
                                 json={"email": email, "password": password}, timeout=10)
        assert response.status_code == 200, response.text
        return {"id": user_id, "email": email, "password": password,
                "headers": {"Authorization": "Bearer " + response.json()["access_token"]}}
    yield create
    engine.dispose()


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture(params=[{"width": 1440, "height": 1000}, {"width": 390, "height": 844}],
                ids=["desktop", "mobile"])
def page(browser, request):
    context = browser.new_context(viewport=request.param, accept_downloads=True)
    page = context.new_page()
    page.set_default_timeout(30000)
    yield page
    context.close()
