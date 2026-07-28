from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def normalize_properties_for_decision_engine(
    properties: list[dict[str, Any]],
    property_type: str,
) -> pd.DataFrame:
    """
    Convert apartments or homes into a shared decision-engine shape.

    This does not mutate the original saved property records.
    """
    df = pd.DataFrame(properties).copy()

    if df.empty:
        return df

    if property_type == "home":
        df["property"] = df.apply(
            lambda row: (
                row.get("display_name")
                or row.get("address")
                or "Unknown Home"
            ),
            axis=1,
        )

        df["price_num"] = df.apply(
            lambda row: row.get("monthly_rent")
            or row.get("sale_price")
            or 0,
            axis=1,
        )

        df["sqft_num"] = pd.to_numeric(
            df.get("square_feet"),
            errors="coerce",
        )

        df["beds_num"] = pd.to_numeric(
            df.get("bedrooms"),
            errors="coerce",
        )

        df["baths_num"] = pd.to_numeric(
            df.get("bathrooms"),
            errors="coerce",
        )

    return df


def render_lifestyle_priorities(
    *,
    key_prefix: str,
    subject_label: str,
) -> dict[str, int]:
    """Render shared lifestyle-priority controls."""

    st.markdown("## 🎯 Lifestyle Priorities")
    st.caption(
        f"Adjust these sliders to personalize your {subject_label.lower()} ranking."
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        commute = st.slider(
            "🚇 Commute",
            1,
            5,
            3,
            key=f"{key_prefix}_commute_priority",
        )
        safety = st.slider(
            "🛡️ Safety",
            1,
            5,
            3,
            key=f"{key_prefix}_safety_priority",
        )

    with col2:
        nightlife = st.slider(
            "🍻 Nightlife",
            1,
            5,
            2,
            key=f"{key_prefix}_nightlife_priority",
        )
        budget = st.slider(
            "💰 Budget",
            1,
            5,
            4,
            key=f"{key_prefix}_budget_priority",
        )

    with col3:
        gym = st.slider(
            "💪 Gym/Fitness",
            1,
            5,
            2,
            key=f"{key_prefix}_gym_priority",
        )

    return {
        "commute": commute,
        "safety": safety,
        "nightlife": nightlife,
        "budget": budget,
        "gym": gym,
    }