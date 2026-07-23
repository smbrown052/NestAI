"""
app/cli/seed_admin.py
One-time command to create the first NestAI administrator account.

Usage (from services/api/):
    python -m app.cli.seed_admin

Reads credentials from environment variables — never from command-line
arguments (which would expose them in shell history / process listings):

    ADMIN_BOOTSTRAP_EMAIL     The admin account email address
    ADMIN_BOOTSTRAP_PASSWORD  A strong password (min 12 characters)

Both variables must be set.  Once the account exists the script exits
safely without modifying it.

Example:
    export ADMIN_BOOTSTRAP_EMAIL=you@example.com
    export ADMIN_BOOTSTRAP_PASSWORD=ChangeMeNow123!
    python -m app.cli.seed_admin
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"ERROR: {name} environment variable is not set.", file=sys.stderr)
        sys.exit(1)
    return value


def main() -> None:
    email = _require_env("ADMIN_BOOTSTRAP_EMAIL")
    password = _require_env("ADMIN_BOOTSTRAP_PASSWORD")

    if len(password) < 12:
        print(
            "ERROR: ADMIN_BOOTSTRAP_PASSWORD must be at least 12 characters.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Import here so the module can be imported without a live DB for testing.
    from passlib.context import CryptContext

    from app.db.session import SessionLocal
    from app.db.models.user import User
    from app.db.models.credits import CreditBalance

    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            if not existing.is_admin:
                existing.is_admin = True
                db.commit()
                print(f"✅  Existing user {email!r} promoted to admin.")
            else:
                print(f"ℹ️   Admin account {email!r} already exists. No changes made.")
            return

        hashed = pwd_ctx.hash(password)
        user = User(
            email=email,
            hashed_password=hashed,
            display_name="Administrator",
            is_active=True,
            is_admin=True,
            tier="premium",
        )
        db.add(user)
        db.flush()  # populate user.id

        balance = CreditBalance(
            user_id=user.id,
            tier="premium",
            credits_remaining=100,
        )
        db.add(balance)
        db.commit()
        print(f"✅  Admin account created for {email!r}")
        print("    Log in at http://localhost:8000/admin")
        print("    Remove ADMIN_BOOTSTRAP_PASSWORD from your environment once done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
