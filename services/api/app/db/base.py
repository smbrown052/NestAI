"""
services/api/app/db/base.py

Declares the shared SQLAlchemy DeclarativeBase and imports every model so
Alembic's autogenerate can discover all tables.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import all models here so Alembic sees them when it loads this module.
# Keep in dependency order (no foreign-key violations on first import).
from app.db.models.user import User  # noqa: E402, F401
from app.db.models.building import Building  # noqa: E402, F401
from app.db.models.unit import Unit  # noqa: E402, F401
from app.db.models.comparison import Comparison  # noqa: E402, F401
from app.db.models.feedback import FeedbackReport  # noqa: E402, F401
from app.db.models.beta_access import BetaAccess  # noqa: E402, F401
from app.db.models.beta_invitation import BetaInvitation  # noqa: E402, F401
from app.db.models.credits import CreditBalance, CreditTransaction  # noqa: E402, F401
from app.db.models.billing import BillingEvent  # noqa: E402, F401
from app.db.models.ai_feedback import AICallLog  # noqa: E402, F401
from app.db.models.audit_log import AuditLog  # noqa: E402, F401
