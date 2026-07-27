"""Plan and signup helpers for NestAI."""

from __future__ import annotations

from dataclasses import dataclass

FREE_PLAN = "free"
BETA_PLAN = "beta"
PREMIUM_PLAN = "premium"
PREMIUM_PLUS_PLAN = "premium_plus"

ALL_PLANS = {FREE_PLAN, BETA_PLAN, PREMIUM_PLAN, PREMIUM_PLUS_PLAN}
PAYMENT_PLANS = {PREMIUM_PLAN, PREMIUM_PLUS_PLAN}
PLANS_REQUIRING_PAYMENT = PAYMENT_PLANS


def normalize_plan(value: str | None) -> str:
    normalized = (value or FREE_PLAN).strip().lower().replace(" ", "_").replace("-", "_")
    return normalized


def is_valid_plan(value: str | None) -> bool:
    return normalize_plan(value) in ALL_PLANS


def plan_requires_payment(plan: str) -> bool:
    return normalize_plan(plan) in PLANS_REQUIRING_PAYMENT


def plan_label(plan: str | None) -> str:
    normalized = normalize_plan(plan)
    return {
        FREE_PLAN: "Free",
        BETA_PLAN: "Beta",
        PREMIUM_PLAN: "Premium",
        PREMIUM_PLUS_PLAN: "Premium Plus",
    }.get(normalized, normalized.title())


def current_plan(user) -> str:
    active_plan = getattr(user, "active_plan", None) or getattr(user, "tier", None) or FREE_PLAN
    return normalize_plan(active_plan)


def requested_plan(user) -> str | None:
    plan = getattr(user, "requested_plan", None)
    return normalize_plan(plan) if plan else None


def set_user_plan(user, plan: str, *, requested: str | None = None, subscription_status: str | None = None) -> None:
    normalized = normalize_plan(plan)
    user.active_plan = normalized
    user.tier = normalized
    user.requested_plan = normalize_plan(requested) if requested else None
    if subscription_status is not None:
        user.subscription_status = subscription_status
