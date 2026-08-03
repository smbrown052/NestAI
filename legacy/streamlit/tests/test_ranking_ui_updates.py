from __future__ import annotations

import pandas as pd

from availability import availability_matches
from ranking import explain_match
from text_parser import filter_units_by_request
from tradeoff_assistant import TradeoffAnalyzer


def test_explain_match_without_profile_prompts_profile_setup() -> None:
    row = pd.Series({"price_num": 2000, "sqft_num": 800})
    assert explain_match(row, {}, 0.0) == [
        "Set up your profile for a personalized match percentage."
    ]


def test_tradeoff_explanation_avoids_internal_score_language() -> None:
    ranked_df = pd.DataFrame(
        [
            {
                "property": "Winner",
                "unit": "101",
                "price_num": 2100,
                "sqft_num": 900,
                "metro_min": 12,
                "available_date": "Now",
                "has_laundry": True,
            },
            {
                "property": "Runner Up",
                "unit": "202",
                "price_num": 2250,
                "sqft_num": 820,
                "metro_min": 20,
                "available_date": "Sep 1",
                "has_laundry": False,
            },
        ]
    )

    explanation = TradeoffAnalyzer(ranked_df).explain_why_winner()
    assert "NestAI Score" not in explanation
    assert "score advantage" not in explanation.lower()
    assert "available sooner" in explanation


def test_available_now_request_keeps_unknown_availability() -> None:
    units = pd.DataFrame(
        [
            {"property": "Known Now", "availability": "Now"},
            {"property": "Unknown", "availability": None},
            {"property": "Later", "availability": "Sep 1"},
        ]
    )

    filtered = filter_units_by_request(units, "available now")
    assert filtered["property"].tolist() == ["Known Now", "Unknown"]


def test_unknown_availability_is_not_treated_as_unavailable() -> None:
    assert availability_matches(None, "Available now") is True
    assert availability_matches("", "Available by selected date", pd.Timestamp("2026-08-20").date()) is True
