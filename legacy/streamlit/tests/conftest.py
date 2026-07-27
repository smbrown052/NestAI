"""
tests/conftest.py
Shared fixtures for NestAI parser tests.

Fixture loading always uses canonical absolute paths (via get_fixture_path)
so tests pass regardless of the current working directory.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure legacy/streamlit is importable without installation
_STREAMLIT_DIR = Path(__file__).resolve().parent.parent
if str(_STREAMLIT_DIR) not in sys.path:
    sys.path.insert(0, str(_STREAMLIT_DIR))


@pytest.fixture(scope="session")
def fixture_1_text() -> str:
    """Pasted Zillow text for 3624 Valley Dr (townhouse for rent, $2,245/mo)."""
    from parser.home_listing import get_fixture_path
    return get_fixture_path("home_example_1.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def fixture_2_text() -> str:
    """Pasted Zillow text for 3507 Martha Custis Dr (house for rent, $2,100/mo)."""
    from parser.home_listing import get_fixture_path
    return get_fixture_path("home_example_2.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def result_1(fixture_1_text):
    """Parsed result for fixture 1."""
    from parser.home_listing import parse_home_listing_text
    return parse_home_listing_text(fixture_1_text)


@pytest.fixture(scope="session")
def result_2(fixture_2_text):
    """Parsed result for fixture 2."""
    from parser.home_listing import parse_home_listing_text
    return parse_home_listing_text(fixture_2_text)
