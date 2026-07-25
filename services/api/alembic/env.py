"""
alembic/env.py — Alembic migration environment.

Reads DATABASE_URL from the environment (or .env file) so no credentials
ever appear in source control.
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# Add the services/api directory to sys.path so `app` is importable.
# Add the services/api directory to sys.path so `app` is importable.
api_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(api_dir))

# Explicitly load services/api/.env
load_dotenv(api_dir / ".env")

config = context.config

database_url = os.environ.get("DATABASE_URL")

if not database_url:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Copy .env.example to .env and fill in your database credentials."
    )
config.set_main_option("sqlalchemy.url", database_url)

# Set up Python logging from alembic.ini.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import the shared Base so all models are registered before autogenerate.
from app.db.base import Base  # noqa: E402

target_metadata = Base.metadata


# ── Migration helpers ─────────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    """Run migrations in offline mode (no live DB connection required)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode (connects to the real DB)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
