"""The privileged bootstrap must not promote an unverified public account."""

import pytest

from app.cli.seed_admin import main
from app.db.models.user import User
from app.db.session import SessionLocal
from app.db.base import Base
from app.db.session import engine


def test_bootstrap_creates_admin_but_refuses_existing_non_admin(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    monkeypatch.setenv("ADMIN_BOOTSTRAP_EMAIL", "  bootstrap@example.com  ")
    monkeypatch.setenv("ADMIN_BOOTSTRAP_PASSWORD", "BootstrapPassword123!")
    main()
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "bootstrap@example.com").one()
        assert user.is_admin
        password_hash = user.hashed_password
    main()
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "bootstrap@example.com").one()
        assert user.hashed_password == password_hash
        user.is_admin = False
        db.commit()
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "bootstrap@example.com").one()
        assert not user.is_admin
        assert user.hashed_password == password_hash
