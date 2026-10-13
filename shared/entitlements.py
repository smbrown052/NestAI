"""Typed monthly account quotas; legacy monetary credits remain independent."""

from dataclasses import asdict, dataclass
import os


@dataclass(frozen=True)
class Limits:
    analyses: int
    properties: int
    ai: int = 0
    enrichment: int = 0
    commute: int = 0
    reports: int = 0


DEFAULTS = {
    "free": Limits(5, 2),
    "premium": Limits(100, 50, 100, 50, 100, 20),
    "premium_plus": Limits(500, 200, 500, 200, 400, 100),
}


def limits_for(plan: str) -> dict[str, int]:
    # Beta status alone never silently grants a paid entitlement.
    defaults = asdict(DEFAULTS.get(plan, DEFAULTS["free"]))
    return {
        key: max(0, int(os.getenv(f"NESTAI_QUOTA_{plan.upper()}_{key.upper()}", value)))
        for key, value in defaults.items()
    }


def features_for(plan: str) -> dict[str, bool]:
    paid = plan in {"premium", "premium_plus"}
    return {
        "basic_comparison": True,
        "advisor": paid,
        "enrichment": paid,
        "commute": paid,
        "negotiation": paid,
        "reports": paid,
        "exports": paid,
        "analytics": plan == "premium_plus",
    }
