"""Import all SQLAlchemy models so metadata registration happens in one place."""

from app.db.models.ai_feedback import AICallLog
from app.db.models.beta_access import BetaAccess
from app.db.models.billing import BillingEvent
from app.db.models.building import Building
from app.db.models.comparison import Comparison
from app.db.models.credits import CreditBalance, CreditTransaction
from app.db.models.feedback import FeedbackReport
from app.db.models.home_details import HomeDetails
from app.db.models.property import Property
from app.db.models.unit import Unit
from app.db.models.usage_event import UsageEvent
from app.db.models.user import User

__all__ = [
    "AICallLog",
    "BetaAccess",
    "BillingEvent",
    "Building",
    "Comparison",
    "CreditBalance",
    "CreditTransaction",
    "FeedbackReport",
    "HomeDetails",
    "Property",
    "Unit",
    "UsageEvent",
    "User",
]