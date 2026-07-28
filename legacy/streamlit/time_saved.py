"""
time_saved.py
Estimates time saved by using NestAI based on tracked session actions.

All values are clearly labeled as estimates.  The underlying assumptions
are centralized here so they can be updated in one place.

Extension point:
    For logged-in users, replace ``get_session_actions`` with a call to
    a database-backed cumulative usage ledger.  The calculation functions
    (``calculate_minutes``, ``format_display``) are backend-agnostic and
    require no changes when persistence is added.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ── Conservative time-saving assumptions (minutes per action) ─────────────────
# All assumptions represent rough estimates of manual effort.
# These can be tuned without changing any call sites.

ASSUMPTIONS: dict[str, int] = {
    # Manually reading, organizing, and noting a single property listing
    "minutes_per_property_organized": 8,
    # Additional time to cross-reference one more property in a comparison
    "minutes_per_additional_comparison": 5,
    # Time to draft a structured decision brief / report manually
    "minutes_per_decision_report": 15,
    # Manually checking commute, Walk Score, and neighborhood data per property
    "minutes_per_enrichment": 5,
    # Drafting a personalized negotiation email and talking points
    "minutes_per_negotiation": 20,
    # Drafting a renewal analysis or lease-review summary
    "minutes_per_renewal": 15,
}

DISCLAIMER = (
    "This is a conservative estimate based on typical time required to manually "
    "organize listing details, compare options, and prepare decision notes. "
    "Your actual time saved may vary."
)


@dataclass
class SessionActions:
    """Snapshot of actions completed in the current session.

    Attributes:
        properties_organized: Number of individual property rows saved to the
            comparison table (not buildings).
        comparisons_done:     True when more than one property has been saved
            (enabling comparison analysis).
        decision_reports_generated: Number of times a Decision Report was
            explicitly generated.
        enrichments_done:     Number of unique buildings enriched with
            neighborhood/commute data.
        negotiations_done:    Number of negotiation scripts generated.
        renewals_done:        Number of renewal analyses generated.
    """

    properties_organized: int = 0
    comparisons_done: bool = False
    decision_reports_generated: int = 0
    enrichments_done: int = 0
    negotiations_done: int = 0
    renewals_done: int = 0


def get_session_actions(session_state) -> SessionActions:
    """Derive completed actions from Streamlit session_state.

    Reads existing session state keys set by the main app — no additional
    tracking instrumentation required.

    Extension point: replace this function body with a database query for
    logged-in users to accumulate totals across sessions.
    """
    comparison_df = session_state.get("comparison_df")
    prop_count: int = len(comparison_df) if comparison_df is not None and not comparison_df.empty else 0

    building_cache = session_state.get("building_cache") or {}
    enrichment_done: bool = bool(session_state.get("enrichment_done"))
    enriched_count: int = len(building_cache) if enrichment_done else 0

    negotiation_outputs = session_state.get("negotiation_outputs") or {}
    neg_count: int = len(negotiation_outputs)

    decision_reports: int = int(session_state.get("nestai_ts_reports_generated", 0))
    renewals: int = int(session_state.get("nestai_ts_renewals_done", 0))

    return SessionActions(
        properties_organized=prop_count,
        comparisons_done=(prop_count > 1),
        decision_reports_generated=decision_reports,
        enrichments_done=enriched_count,
        negotiations_done=neg_count,
        renewals_done=renewals,
    )


def calculate_minutes(actions: SessionActions, assumptions: Optional[dict] = None) -> int:
    """Return total estimated minutes saved (non-negative integer).

    Uses ``ASSUMPTIONS`` by default; pass a custom dict for testing.
    Avoids double-counting: the first property's base cost is always
    included; additional properties only add the incremental comparison cost.
    """
    a = assumptions or ASSUMPTIONS
    minutes = 0

    # Base cost per property organized
    minutes += actions.properties_organized * a["minutes_per_property_organized"]

    # Additional comparison time for properties 2+ (incremental only)
    if actions.comparisons_done and actions.properties_organized > 1:
        extra = actions.properties_organized - 1
        minutes += extra * a["minutes_per_additional_comparison"]

    # Decision reports
    minutes += actions.decision_reports_generated * a["minutes_per_decision_report"]

    # Enrichment (commute + neighborhood data)
    minutes += actions.enrichments_done * a["minutes_per_enrichment"]

    # Negotiation scripts
    minutes += actions.negotiations_done * a["minutes_per_negotiation"]

    # Renewal analyses
    minutes += actions.renewals_done * a["minutes_per_renewal"]

    return max(0, minutes)


def format_display(total_minutes: int) -> str:
    """Format total minutes as a human-readable string.

    Examples:
        0  → "0 min"
        45 → "45 min"
        60 → "1 hr"
        90 → "1 hr 30 min"
    """
    if total_minutes <= 0:
        return "0 min"
    hours, minutes = divmod(total_minutes, 60)
    if hours == 0:
        return f"{minutes} min"
    if minutes == 0:
        return f"{hours} hr"
    return f"{hours} hr {minutes} min"


def build_breakdown(actions: SessionActions, assumptions: Optional[dict] = None) -> list[str]:
    """Return human-readable list of contributing actions (non-zero only).

    Used to populate the "Based on:" block in the UI.
    """
    a = assumptions or ASSUMPTIONS
    lines: list[str] = []

    if actions.properties_organized > 0:
        lines.append(f"{actions.properties_organized} propert{'y' if actions.properties_organized == 1 else 'ies'} organized")

    if actions.comparisons_done and actions.properties_organized > 1:
        lines.append(f"{actions.properties_organized - 1} additional comparison{'s' if actions.properties_organized > 2 else ''}")

    if actions.decision_reports_generated > 0:
        lines.append(
            f"{actions.decision_reports_generated} Decision Report{'s' if actions.decision_reports_generated > 1 else ''} generated"
        )

    if actions.enrichments_done > 0:
        lines.append(
            f"{actions.enrichments_done} neighborhood enrichment{'s' if actions.enrichments_done > 1 else ''} completed"
        )

    if actions.negotiations_done > 0:
        lines.append(
            f"{actions.negotiations_done} negotiation script{'s' if actions.negotiations_done > 1 else ''} generated"
        )

    if actions.renewals_done > 0:
        lines.append(
            f"{actions.renewals_done} renewal anal{'yses' if actions.renewals_done > 1 else 'ysis'} completed"
        )

    return lines
