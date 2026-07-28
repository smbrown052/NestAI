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
        "badge": "Beta · Early Access",
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
/* ── NestAI Design Tokens: Purple System ─────────────────────────────────── */
:root {
    /* Brand colors */
    --nest-primary: #7c3aed;           /* rich purple */
    --nest-primary-deep: #6d28d9;      /* deep purple */
    --nest-primary-light: rgba(124, 58, 237, 0.08);   /* light purple surface */
    --nest-accent: #8b5cf6;            /* violet accent */

    /* Page and surface */
    --nest-bg: #faf9fb;                /* warm near-white */
    --nest-surface: rgba(255, 255, 255, 0.97);
    --nest-surface-strong: #ffffff;
    --nest-surface-muted: rgba(245, 243, 255, 0.70);

    /* Borders */
    --nest-border: rgba(109, 40, 217, 0.10);
    --nest-border-strong: rgba(124, 58, 237, 0.22);
    --nest-border-neutral: rgba(15, 23, 42, 0.10);

    /* Text */
    --nest-text: #1a1028;              /* deep charcoal with slight purple */
    --nest-text-soft: #4a4060;         /* secondary text */
    --nest-text-muted: #7c6f8a;        /* muted text */

    /* Semantic */
    --nest-success: #059669;
    --nest-warning: #d97706;
    --nest-locked: #94a3b8;

    /* Tier-specific */
    --nest-premium: #5b21b6;           /* premium purple */
    --nest-premium-plus: #4c1d95;      /* deep premium plus */
    --nest-pp-gradient: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%);
    --nest-pp-surface: linear-gradient(145deg, rgba(124,58,237,0.06) 0%, rgba(79,70,229,0.04) 100%);

    /* Shadows */
    --nest-shadow: 0 18px 42px rgba(109, 40, 217, 0.10);
    --nest-shadow-soft: 0 10px 24px rgba(109, 40, 217, 0.07);

    /* Radii */
    --nest-radius-lg: 24px;
    --nest-radius-md: 18px;
    --nest-radius-sm: 14px;
}

/* ── Page background ─────────────────────────────────────────────────────── */
.stApp {
    background:
        radial-gradient(circle at top left, rgba(124, 58, 237, 0.06), transparent 40%),
        linear-gradient(180deg, #faf9fb 0%, #f5f3ff 40%, #faf9fb 100%);
    color: var(--nest-text);
}

[data-testid="stHeader"] {
    background: rgba(250, 249, 251, 0.85);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--nest-border);
}

/* ── Sidebar (keeps dark for contrast) ──────────────────────────────────── */
[data-testid="stSidebar"] {
    background:
        linear-gradient(180deg, rgba(15, 10, 28, 0.99) 0%, rgba(26, 16, 40, 0.97) 100%);
    border-right: 1px solid rgba(124, 58, 237, 0.18);
}

[data-testid="stSidebar"] * {
    color: #e2d9f3;
}

[data-testid="stSidebar"] [data-testid="stMetricValue"],
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p strong {
    color: #f5f0ff;
}

/* ── Layout ──────────────────────────────────────────────────────────────── */
.block-container {
    padding-top: 2rem;
    padding-bottom: 3rem;
}

h1, h2, h3, h4, h5, h6, label {
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

/* ── Buttons ─────────────────────────────────────────────────────────────── */
[data-testid="stButton"] > button,
[data-testid="baseButton-secondary"] {
    border-radius: 999px;
    min-height: 2.9rem;
    border: 1px solid rgba(124, 58, 237, 0.16);
    background: rgba(255, 255, 255, 0.95);
    color: var(--nest-text);
    font-weight: 600;
    box-shadow: 0 4px 14px rgba(109, 40, 217, 0.08);
    transition: border-color 0.15s, transform 0.15s, box-shadow 0.15s;
}

[data-testid="stButton"] > button[kind="primary"] {
    background: var(--nest-pp-gradient);
    color: #fff;
    border-color: transparent;
    box-shadow: 0 6px 18px rgba(124, 58, 237, 0.30);
}

[data-testid="stButton"] > button:hover {
    border-color: rgba(124, 58, 237, 0.40);
    transform: translateY(-1px);
    box-shadow: 0 8px 22px rgba(109, 40, 217, 0.14);
}

[data-testid="stButton"] > button[kind="primary"]:hover {
    box-shadow: 0 10px 28px rgba(124, 58, 237, 0.42);
}

[data-testid="stButton"] > button:focus,
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus,
[data-baseweb="select"] input:focus {
    outline: 3px solid rgba(124, 58, 237, 0.20) !important;
    border-color: rgba(124, 58, 237, 0.50) !important;
    box-shadow: 0 0 0 1px rgba(124, 58, 237, 0.24) !important;
}

/* ── Base cards ──────────────────────────────────────────────────────────── */
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
    background: linear-gradient(135deg, rgba(255,255,255,0.97) 0%, rgba(245,243,255,0.94) 100%);
    border-color: var(--nest-border);
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

/* ── Typography helpers ──────────────────────────────────────────────────── */
.nestai-eyebrow {
    font-size: 0.78rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--nest-primary);
    font-weight: 700;
    opacity: 0.85;
}

.nestai-subtle {
    color: var(--nest-text-soft);
    font-size: 0.95rem;
}

/* ── Plan tier badges ────────────────────────────────────────────────────── */
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

/* Free — neutral, clean */
.tier-free {
    background: rgba(226, 232, 240, 0.85);
    color: #334155;
    border-color: rgba(100, 116, 139, 0.18);
}

/* Beta — violet early-access */
.tier-beta {
    background: rgba(139, 92, 246, 0.10);
    color: #5b21b6;
    border-color: rgba(139, 92, 246, 0.20);
}

/* Premium — purple accents */
.tier-premium {
    background: rgba(124, 58, 237, 0.09);
    color: #5b21b6;
    border-color: rgba(124, 58, 237, 0.18);
}

/* Premium Plus — purple-to-indigo gradient treatment */
.tier-premium-plus {
    background: linear-gradient(135deg, rgba(124, 58, 237, 0.14) 0%, rgba(79, 70, 229, 0.10) 100%);
    color: #4c1d95;
    border-color: rgba(124, 58, 237, 0.22);
    font-weight: 800;
}

/* ── Plan cards (pricing page) ───────────────────────────────────────────── */
.nestai-tier-card {
    padding: 1.25rem;
    min-height: 100%;
}

.nestai-tier-card.tier-premium {
    border-color: rgba(124, 58, 237, 0.20);
    box-shadow: 0 16px 38px rgba(124, 58, 237, 0.10);
}

.nestai-tier-card.tier-premium-plus {
    background: linear-gradient(175deg, rgba(255,255,255,0.98) 0%, rgba(245,243,255,0.97) 100%);
    border-color: rgba(124, 58, 237, 0.28);
    box-shadow: 0 22px 52px rgba(109, 40, 217, 0.18);
}

.nestai-tier-card.recommended {
    transform: translateY(-4px);
    border-color: rgba(124, 58, 237, 0.38);
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

/* ── Feature lists ───────────────────────────────────────────────────────── */
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

/* ── Metric cards ────────────────────────────────────────────────────────── */
.nestai-grid-gap { gap: 0.85rem; }

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

/* ── Pills / feature tags ────────────────────────────────────────────────── */
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
    background: var(--nest-primary-light);
    color: #5b21b6;
}

.nestai-pill-positive {
    background: rgba(5, 150, 105, 0.10);
    color: #065f46;
}

.nestai-pill-warning {
    background: rgba(217, 119, 6, 0.14);
    color: #92400e;
}

.nestai-pill-premium {
    background: rgba(124, 58, 237, 0.10);
    color: #5b21b6;
}

.nestai-pill-locked {
    background: rgba(148, 163, 184, 0.14);
    color: #475569;
}

/* ── Ranking cards ───────────────────────────────────────────────────────── */
.nestai-ranking-card.top-ranked {
    background: linear-gradient(175deg, rgba(255,255,255,0.99) 0%, rgba(245,243,255,0.96) 100%);
    border-color: rgba(124, 58, 237, 0.22);
}

.nestai-ranking-card.tier-premium-plus {
    background: linear-gradient(175deg, rgba(255,255,255,0.99) 0%, rgba(245,243,255,0.98) 100%);
    border-color: rgba(109, 40, 217, 0.20);
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
    color: var(--nest-primary);
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

/* ── Upgrade / locked cards ──────────────────────────────────────────────── */
.nestai-upgrade-card {
    background: linear-gradient(135deg, rgba(255,255,255,0.98) 0%, rgba(245,243,255,0.95) 100%);
    border-color: rgba(124, 58, 237, 0.14);
}

.nestai-upgrade-card.tier-premium-plus {
    background: linear-gradient(135deg, rgba(255,255,255,0.98) 0%, rgba(245,243,255,0.97) 100%);
    border-color: rgba(124, 58, 237, 0.22);
}

.nestai-locked-card {
    background: rgba(248, 246, 255, 0.80);
    border-style: dashed;
    border-color: rgba(124, 58, 237, 0.14);
}

.nestai-section-note {
    margin: 0.1rem 0 0.7rem 0;
    color: var(--nest-text-soft);
}

/* ── Premium Plus Unlocked section ──────────────────────────────────────── */
.nestai-pp-section {
    background: linear-gradient(155deg, rgba(245,243,255,0.80) 0%, rgba(238,236,254,0.70) 100%);
    border: 1px solid rgba(124, 58, 237, 0.18);
    border-radius: var(--nest-radius-lg);
    padding: 1.5rem 1.6rem;
    margin-bottom: 1.5rem;
}

.nestai-pp-section-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 1rem;
}

.nestai-pp-title {
    font-size: 1.1rem;
    font-weight: 800;
    color: var(--nest-premium-plus);
    margin: 0;
}

.nestai-pp-feature-card {
    background: rgba(255,255,255,0.95);
    border: 1px solid rgba(124, 58, 237, 0.14);
    border-radius: var(--nest-radius-md);
    padding: 1.1rem 1.15rem;
    height: 100%;
    box-shadow: 0 6px 18px rgba(109, 40, 217, 0.06);
    transition: box-shadow 0.15s, border-color 0.15s;
}

.nestai-pp-feature-card:hover {
    border-color: rgba(124, 58, 237, 0.26);
    box-shadow: 0 10px 26px rgba(109, 40, 217, 0.10);
}

.nestai-pp-feature-card.coming-soon {
    background: rgba(248, 246, 255, 0.70);
    border-color: rgba(124, 58, 237, 0.08);
    box-shadow: none;
    opacity: 0.82;
}

.nestai-pp-card-icon {
    font-size: 1.55rem;
    margin-bottom: 0.35rem;
    line-height: 1;
}

.nestai-pp-card-title {
    font-size: 0.98rem;
    font-weight: 700;
    color: var(--nest-text);
    margin: 0 0 0.3rem 0;
}

.nestai-pp-card-value {
    font-size: 0.87rem;
    color: var(--nest-text-soft);
    margin: 0 0 0.55rem 0;
    line-height: 1.45;
}

.nestai-pp-status-badge {
    display: inline-flex;
    align-items: center;
    padding: 0.22rem 0.6rem;
    border-radius: 999px;
    font-size: 0.73rem;
    font-weight: 700;
    gap: 0.3rem;
}

.nestai-pp-status-available {
    background: rgba(5, 150, 105, 0.10);
    color: #065f46;
    border: 1px solid rgba(5, 150, 105, 0.18);
}

.nestai-pp-status-coming-soon {
    background: rgba(109, 40, 217, 0.08);
    color: #6d28d9;
    border: 1px solid rgba(109, 40, 217, 0.14);
}

.nestai-pp-status-early-access {
    background: rgba(139, 92, 246, 0.10);
    color: #5b21b6;
    border: 1px solid rgba(139, 92, 246, 0.18);
}

/* Locked preview for non-PP users */
.nestai-pp-locked-section {
    background: rgba(245, 243, 255, 0.50);
    border: 1px dashed rgba(124, 58, 237, 0.20);
    border-radius: var(--nest-radius-lg);
    padding: 1.5rem 1.6rem;
    margin-bottom: 1.5rem;
}

.nestai-pp-locked-preview {
    filter: blur(2px);
    opacity: 0.45;
    pointer-events: none;
    user-select: none;
}

/* ── Time Saved display ──────────────────────────────────────────────────── */
.nestai-time-saved-card {
    background: linear-gradient(135deg, rgba(124, 58, 237, 0.07) 0%, rgba(79, 70, 229, 0.05) 100%);
    border: 1px solid rgba(124, 58, 237, 0.16);
    border-radius: var(--nest-radius-md);
    padding: 1rem 1.1rem;
    margin-bottom: 0.85rem;
}

.nestai-time-saved-value {
    font-size: 1.6rem;
    font-weight: 800;
    color: var(--nest-premium-plus);
    margin: 0.15rem 0 0.1rem 0;
}

.nestai-time-saved-label {
    font-size: 0.78rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--nest-primary);
    opacity: 0.85;
}

.nestai-time-saved-note {
    font-size: 0.82rem;
    color: var(--nest-text-muted);
    margin-top: 0.15rem;
    font-style: italic;
}

/* ── Plan-switch success banner ──────────────────────────────────────────── */
.nestai-unlock-banner {
    background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%);
    color: #ffffff;
    border-radius: var(--nest-radius-md);
    padding: 0.9rem 1.2rem;
    margin-bottom: 1rem;
    font-weight: 600;
    font-size: 0.98rem;
    display: flex;
    align-items: center;
    gap: 0.65rem;
    box-shadow: 0 8px 22px rgba(124, 58, 237, 0.32);
}

/* ── Responsive ──────────────────────────────────────────────────────────── */
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

    .nestai-pp-section,
    .nestai-pp-locked-section {
        padding: 1.1rem 1rem;
    }
}
</style>
        """,
        unsafe_allow_html=True,
    )
