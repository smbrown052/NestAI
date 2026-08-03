"""Small UI-state helpers for NestAI Streamlit pages."""

from __future__ import annotations


def get_navigation_options(authenticated: bool) -> list[str]:
    _ = authenticated
    return [
        "Home",
        "Apartment Search",
        "Houses",
        "Profile",
        "Why NestAI",
        "How to Use NestAI",
    ]


def get_account_type_options() -> list[str]:
    return ["free", "beta", "premium", "premium_plus"]


def plan_display_name(plan: str) -> str:
    return {
        "free": "Free",
        "beta": "Beta",
        "premium": "Premium",
        "premium_plus": "Premium Plus",
        "owner_test": "Owner Test",
    }.get(plan, plan.title())