from __future__ import annotations

from html import escape

import streamlit as st


PLAN_META = {
    "free": {
        "label": "Free",
        "badge": "Free",
        "class_name": "tier-free",
        "accent": "Clean essentials",
    },
    "beta": {
        "label": "Beta",
        "badge": "Beta",
        "class_name": "tier-beta",
        "accent": "Early access",
    },
    "premium": {
        "label": "Premium",
        "badge": "Premium",
        "class_name": "tier-premium",
        "accent": "Decision intelligence",
    },
    "premium_plus": {
        "label": "Premium Plus",
        "badge": "Premium Plus",
        "class_name": "tier-premium-plus",
        "accent": "Advanced intelligence",
    },
}


def normalize_plan(plan: str | None) -> str:
    raw = (plan or "free").strip().lower().replace(" ", "_").replace("-", "_")
    mapping = {
        "free": "free",
        "plan_free": "free",
        "beta": "beta",
        "plan_beta": "beta",
        "premium": "premium",
        "plan_premium": "premium",
        "premium_plus": "premium_plus",
        "plan_premium_plus": "premium_plus",
        "owner_test": "premium_plus",
        "premiumplus": "premium_plus",
    }
    return mapping.get(raw, raw if raw in PLAN_META else "free")


def plan_meta(plan: str | None) -> dict[str, str]:
    return PLAN_META[normalize_plan(plan)]


def tier_class(plan: str | None) -> str:
    return plan_meta(plan)["class_name"]


def render_badge(plan: str | None, *, label: str | None = None, icon: str | None = None) -> None:
    meta = plan_meta(plan)
    display = escape(label or meta["badge"])
    icon_html = f"<span>{escape(icon)}</span>" if icon else ""
    st.markdown(
        (
            f"<div class='nestai-badge {meta['class_name']}'>"
            f"{icon_html}<span>{display}</span>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def metric_card_html(label: str, value: str, helper: str = "", tier: str = "free") -> str:
    helper_html = f"<div class='nestai-metric-helper'>{escape(helper)}</div>" if helper else ""
    return (
        f"<div class='nestai-metric-card {tier_class(tier)}'>"
        f"<div class='nestai-metric-label'>{escape(label)}</div>"
        f"<div class='nestai-metric-value'>{escape(value)}</div>"
        f"{helper_html}"
        "</div>"
    )


def feature_pill(text: str, tone: str = "default") -> str:
    safe_tone = tone if tone in {"default", "positive", "warning", "premium", "locked"} else "default"
    return f"<span class='nestai-pill nestai-pill-{safe_tone}'>{escape(text)}</span>"


def inject_global_styles() -> None:
    st.markdown(
        """
<style>
:root {
    --nest-bg: #0b1220;
    --nest-bg-alt: #111a2d;
    --nest-surface: rgba(255, 255, 255, 0.94);
    --nest-surface-strong: #ffffff;
    --nest-surface-muted: rgba(241, 245, 249, 0.88);
    --nest-border: rgba(15, 23, 42, 0.10);
    --nest-border-strong: rgba(59, 130, 246, 0.24);
    --nest-text: #0f172a;
    --nest-text-soft: #475569;
    --nest-text-muted: #64748b;
    --nest-primary: #2563eb;
    --nest-primary-deep: #1d4ed8;
    --nest-accent: #0f766e;
    --nest-success: #0f766e;
    --nest-warning: #b45309;
    --nest-locked: #64748b;
    --nest-premium: #312e81;
    --nest-premium-plus: #4c1d95;
    --nest-shadow: 0 18px 42px rgba(15, 23, 42, 0.12);
    --nest-shadow-soft: 0 10px 24px rgba(15, 23, 42, 0.08);
    --nest-radius-lg: 24px;
    --nest-radius-md: 18px;
    --nest-radius-sm: 14px;
}

.stApp {
    background:
        radial-gradient(circle at top, rgba(37, 99, 235, 0.10), transparent 26%),
        linear-gradient(180deg, #eff4ff 0%, #f8fafc 18%, #eef2ff 100%);
    color: var(--nest-text);
}

[data-testid="stHeader"] {
    background: rgba(248, 250, 252, 0.78);
    backdrop-filter: blur(10px);
}

[data-testid="stSidebar"] {
    background:
        linear-gradient(180deg, rgba(11, 18, 32, 0.98) 0%, rgba(15, 23, 42, 0.96) 100%);
    border-right: 1px solid rgba(148, 163, 184, 0.18);
}

[data-testid="stSidebar"] * {
    color: #e2e8f0;
}

[data-testid="stSidebar"] [data-testid="stMetricValue"],
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p strong {
    color: #f8fafc;
}

.block-container {
    padding-top: 2rem;
    padding-bottom: 3rem;
}

h1, h2, h3, h4, h5, h6, p, li, label {
    color: var(--nest-text);
}

p, li, [data-testid="stCaptionContainer"] {
    color: var(--nest-text-soft);
}

[data-testid="stMetric"],
[data-testid="stExpander"],
[data-testid="stForm"],
[data-testid="stDataFrame"],
div[data-testid="stVerticalBlockBorderWrapper"] > div {
    border-radius: var(--nest-radius-md);
}

[data-testid="stMetric"] {
    background: var(--nest-surface);
    border: 1px solid var(--nest-border);
    box-shadow: var(--nest-shadow-soft);
    padding: 0.9rem 1rem;
}

[data-testid="stButton"] > button,
[data-testid="baseButton-secondary"] {
    border-radius: 999px;
    min-height: 2.9rem;
    border: 1px solid rgba(37, 99, 235, 0.14);
    background: rgba(255, 255, 255, 0.92);
    color: var(--nest-text);
    font-weight: 600;
    box-shadow: 0 8px 20px rgba(15, 23, 42, 0.07);
}

[data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(135deg, var(--nest-primary) 0%, var(--nest-primary-deep) 100%);
    color: #fff;
    border-color: transparent;
}

[data-testid="stButton"] > button:hover {
    border-color: rgba(37, 99, 235, 0.35);
    transform: translateY(-1px);
}

[data-testid="stButton"] > button:focus,
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus,
[data-baseweb="select"] input:focus {
    outline: 3px solid rgba(37, 99, 235, 0.18) !important;
    border-color: rgba(37, 99, 235, 0.45) !important;
    box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.22) !important;
}

.nestai-hero,
.nestai-surface,
.nestai-tier-card,
.nestai-ranking-card,
.nestai-decision-card,
.nestai-profile-card,
.nestai-upgrade-card,
.nestai-locked-card,
.nestai-home-card,
.nestai-comparison-card {
    background: var(--nest-surface);
    border: 1px solid var(--nest-border);
    border-radius: var(--nest-radius-lg);
    box-shadow: var(--nest-shadow);
}

.nestai-hero {
    padding: 1.5rem 1.6rem;
    background:
        linear-gradient(135deg, rgba(255,255,255,0.96) 0%, rgba(239,246,255,0.94) 100%);
    margin-bottom: 1rem;
}

.nestai-hero h2,
.nestai-tier-card h3,
.nestai-ranking-card h3,
.nestai-profile-card h3,
.nestai-upgrade-card h3,
.nestai-home-card h3,
.nestai-comparison-card h3 {
    margin: 0;
    color: var(--nest-text);
}

.nestai-eyebrow {
    font-size: 0.78rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--nest-text-muted);
    font-weight: 700;
}

.nestai-subtle {
    color: var(--nest-text-soft);
    font-size: 0.95rem;
}

.nestai-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.4rem 0.75rem;
    border-radius: 999px;
    font-size: 0.77rem;
    font-weight: 700;
    border: 1px solid transparent;
    margin-bottom: 0.65rem;
}

.tier-free {
    background: rgba(226, 232, 240, 0.9);
    color: #334155;
    border-color: rgba(100, 116, 139, 0.18);
}

.tier-beta {
    background: rgba(12, 148, 136, 0.10);
    color: #115e59;
    border-color: rgba(15, 118, 110, 0.16);
}

.tier-premium {
    background: rgba(49, 46, 129, 0.10);
    color: #312e81;
    border-color: rgba(67, 56, 202, 0.18);
}

.tier-premium-plus {
    background:
        linear-gradient(135deg, rgba(76, 29, 149, 0.12) 0%, rgba(29, 78, 216, 0.10) 100%);
    color: #4c1d95;
    border-color: rgba(76, 29, 149, 0.20);
}

.nestai-tier-card {
    padding: 1.25rem;
    min-height: 100%;
}

.nestai-tier-card.tier-premium {
    border-color: rgba(67, 56, 202, 0.18);
}

.nestai-tier-card.tier-premium-plus {
    background:
        linear-gradient(180deg, rgba(255,255,255,0.96) 0%, rgba(245,243,255,0.96) 100%);
    border-color: rgba(76, 29, 149, 0.22);
    box-shadow: 0 20px 48px rgba(76, 29, 149, 0.16);
}

.nestai-tier-card.recommended {
    transform: translateY(-4px);
    border-color: rgba(37, 99, 235, 0.34);
}

.nestai-tier-card .price {
    font-size: 2rem;
    font-weight: 800;
    color: var(--nest-text);
}

.nestai-tier-card .period {
    color: var(--nest-text-muted);
    margin-left: 0.25rem;
}

.nestai-feature-list,
.nestai-muted-list {
    margin: 0.8rem 0 0 0;
    padding: 0;
    list-style: none;
}

.nestai-feature-list li,
.nestai-muted-list li {
    margin: 0.48rem 0;
    padding-left: 1.4rem;
    position: relative;
    line-height: 1.45;
}

.nestai-feature-list li::before {
    content: "✓";
    position: absolute;
    left: 0;
    color: var(--nest-success);
    font-weight: 800;
}

.nestai-muted-list li::before {
    content: "•";
    position: absolute;
    left: 0;
    color: var(--nest-locked);
}

.nestai-grid-gap {
    gap: 0.85rem;
}

.nestai-metric-card,
.nestai-decision-card,
.nestai-profile-card,
.nestai-home-card,
.nestai-comparison-card,
.nestai-upgrade-card,
.nestai-locked-card,
.nestai-ranking-card {
    padding: 1rem 1.1rem;
    margin-bottom: 0.85rem;
}

.nestai-metric-label {
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--nest-text-muted);
    font-weight: 700;
}

.nestai-metric-value {
    font-size: 1.45rem;
    font-weight: 800;
    color: var(--nest-text);
    margin-top: 0.2rem;
}

.nestai-metric-helper {
    font-size: 0.88rem;
    color: var(--nest-text-soft);
    margin-top: 0.3rem;
}

.nestai-pill {
    display: inline-flex;
    align-items: center;
    padding: 0.28rem 0.65rem;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 700;
    margin: 0.2rem 0.35rem 0.2rem 0;
}

.nestai-pill-default {
    background: rgba(37, 99, 235, 0.08);
    color: #1d4ed8;
}

.nestai-pill-positive {
    background: rgba(15, 118, 110, 0.11);
    color: #0f766e;
}

.nestai-pill-warning {
    background: rgba(245, 158, 11, 0.16);
    color: #92400e;
}

.nestai-pill-premium {
    background: rgba(67, 56, 202, 0.10);
    color: #4338ca;
}

.nestai-pill-locked {
    background: rgba(100, 116, 139, 0.12);
    color: #475569;
}

.nestai-ranking-card.top-ranked {
    background:
        linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(239,246,255,0.95) 100%);
    border-color: rgba(37, 99, 235, 0.28);
}

.nestai-ranking-card.tier-premium-plus {
    background:
        linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(245,243,255,0.98) 100%);
    border-color: rgba(76, 29, 149, 0.18);
}

.nestai-ranking-header,
.nestai-flex-between {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
}

.nestai-rank-number {
    font-size: 0.84rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--nest-primary-deep);
}

.nestai-ranking-score {
    font-size: 1.75rem;
    font-weight: 800;
    color: var(--nest-text);
}

.nestai-ranking-subtitle,
.nestai-ranking-meta {
    color: var(--nest-text-soft);
    font-size: 0.94rem;
}

.nestai-upgrade-card {
    background:
        linear-gradient(135deg, rgba(255,255,255,0.98) 0%, rgba(239,246,255,0.95) 100%);
}

.nestai-upgrade-card.tier-premium-plus {
    background:
        linear-gradient(135deg, rgba(255,255,255,0.98) 0%, rgba(245,243,255,0.96) 100%);
}

.nestai-locked-card {
    background: rgba(248, 250, 252, 0.92);
    border-style: dashed;
}

.nestai-section-note {
    margin: 0.1rem 0 0.7rem 0;
    color: var(--nest-text-soft);
}

@media (max-width: 900px) {
    .block-container {
        padding-top: 1.2rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }

    .nestai-flex-between,
    .nestai-ranking-header {
        flex-direction: column;
    }
}
</style>
        """,
        unsafe_allow_html=True,
    )
