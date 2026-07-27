"""Small UI-state helpers for NestAI Streamlit pages."""

from __future__ import annotations


def get_navigation_options(authenticated: bool) -> list[str]:
    options = ["Apartments", "Houses", "Pricing", "Profile"]
    if not authenticated:
        options.extend(["Login", "Create Account"])
    return options


def get_account_type_options() -> list[str]:
    return ["free", "beta", "premium", "premium_plus"]


def plan_display_name(plan: str) -> str:
    return {
        "free": "Free",
        "beta": "Beta",
        "premium": "Premium",
        "premium_plus": "Premium Plus",
    }.get(plan, plan.title())