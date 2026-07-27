"""
test_home_storage.py
Tests for home_storage.py — SQLite persistence for saved homes.

These tests use a temporary database file; the production database is not touched.
"""

import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

# Ensure legacy/streamlit is on the path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest

# ── Streamlit mock ────────────────────────────────────────────────────────────

import types

class _MockState(dict):
    def __getattr__(self, name):
        return self[name] if name in self else None
    def __setattr__(self, name, value):
        self[name] = value

_mock_st = types.ModuleType("streamlit")
_state = _MockState()
_mock_st.session_state = _state
sys.modules["streamlit"] = _mock_st


# ── Patch DB path to a temp file ──────────────────────────────────────────────

import home_storage

_tmp_db = Path(tempfile.mkdtemp()) / "test_homes.db"

@pytest.fixture(autouse=True)
def _use_tmp_db(monkeypatch, tmp_path):
    """Redirect all DB operations to an isolated temp database."""
    db_file = tmp_path / "test_homes.db"
    monkeypatch.setattr(home_storage, "_DB_PATH", db_file)
    _state.clear()
    _state["nestai_session_id"] = "test-session-001"
    yield
    # DB file is automatically removed by tmp_path cleanup


def _make_result(**kwargs):
    """Build a minimal ParsedHomeResult for testing."""
    from parser.home_listing import ParsedHomeResult
    defaults = dict(
        property_type="RENTAL_HOME",
        address="123 Test St, Alexandria, VA 22302",
        city="Alexandria",
        state="VA",
        postal_code="22302",
        display_name="123 Test St",
        monthly_rent=2000,
        sale_price=None,
        bedrooms=2,
        bathrooms=1.0,
        square_feet=900,
        available_date="Now",
        pets_policy="No pets",
        cooling="Central air",
        heating="Forced air",
        parking="Street",
        laundry="In unit",
        walk_score=70,
        transit_score=60,
        bike_score=65,
        days_on_zillow=5,
        hours_on_zillow=None,
        description="A nice place.",
        features=["Hardwood floors", "Dishwasher"],
        schools=["Lincoln Elementary"],
        warnings=[],
        price_raw="$2,000/mo",
        property_subtype="Townhouse",
    )
    defaults.update(kwargs)
    return ParsedHomeResult(**defaults)


# ── Schema creation ────────────────────────────────────────────────────────────

class TestSchema:
    def test_schema_creates_tables(self):
        home_storage._ensure_schema()
        import sqlite3
        conn = sqlite3.connect(str(home_storage._DB_PATH))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "saved_homes" in tables
        assert "home_events" in tables


# ── save_home ─────────────────────────────────────────────────────────────────

class TestSaveHome:
    def test_save_returns_id(self):
        result = _make_result()
        home_id = home_storage.save_home(result)
        assert isinstance(home_id, int)
        assert home_id > 0

    def test_saved_home_is_active(self):
        home_storage.save_home(_make_result())
        assert home_storage.count_active_homes() == 1

    def test_saved_home_address_stored(self):
        result = _make_result(address="456 Oak Ave, Springfield, IL 62701")
        home_id = home_storage.save_home(result)
        row = home_storage.get_home_by_id(home_id)
        assert row is not None
        assert "456 Oak Ave" in row["address"]

    def test_saved_home_monthly_rent_stored(self):
        result = _make_result(monthly_rent=1850)
        home_id = home_storage.save_home(result)
        row = home_storage.get_home_by_id(home_id)
        assert row["monthly_rent"] == 1850

    def test_saved_home_features_stored_as_json(self):
        result = _make_result(features=["Balcony", "Gym"])
        home_id = home_storage.save_home(result)
        row = home_storage.get_home_by_id(home_id)
        features = json.loads(row["features_json"])
        assert "Balcony" in features

    def test_raw_source_text_is_capped(self):
        big_text = "x" * 200_000
        result = _make_result()
        home_id = home_storage.save_home(result, raw_source_text=big_text)
        row = home_storage.get_home_by_id(home_id)
        # stored value should be at most 128KB (HTML escaped)
        assert len(row["raw_source_text"]) <= home_storage._MAX_RAW_TEXT_BYTES + 100  # small escape overhead

    def test_raw_source_text_html_escaped(self):
        result = _make_result()
        home_id = home_storage.save_home(result, raw_source_text="<script>alert(1)</script>")
        row = home_storage.get_home_by_id(home_id)
        assert "<script>" not in row["raw_source_text"]
        assert "&lt;script&gt;" in row["raw_source_text"]

    def test_save_multiple_homes(self):
        for i in range(3):
            home_storage.save_home(_make_result(address=f"{i} Main St"))
        assert home_storage.count_active_homes() == 3


# ── archive_home ──────────────────────────────────────────────────────────────

class TestArchiveHome:
    def test_archive_removes_from_active(self):
        home_id = home_storage.save_home(_make_result())
        home_storage.archive_home(home_id)
        assert home_storage.count_active_homes() == 0

    def test_archived_home_appears_in_list(self):
        home_id = home_storage.save_home(_make_result())
        home_storage.archive_home(home_id)
        archived = home_storage.list_archived_homes()
        assert any(h["id"] == home_id for h in archived)

    def test_archived_home_not_in_active_list(self):
        home_id = home_storage.save_home(_make_result())
        home_storage.archive_home(home_id)
        active = home_storage.list_active_homes()
        assert not any(h["id"] == home_id for h in active)

    def test_cannot_archive_other_sessions_home(self):
        home_id = home_storage.save_home(_make_result())
        # Switch session
        _state["nestai_session_id"] = "other-session"
        home_storage.archive_home(home_id)   # should silently do nothing
        _state["nestai_session_id"] = "test-session-001"
        # Home should still be active
        assert home_storage.count_active_homes() == 1


# ── restore_home ──────────────────────────────────────────────────────────────

class TestRestoreHome:
    def test_restore_makes_home_active_again(self):
        home_id = home_storage.save_home(_make_result())
        home_storage.archive_home(home_id)
        home_storage.restore_home(home_id)
        assert home_storage.count_active_homes() == 1

    def test_restored_home_not_in_archived_list(self):
        home_id = home_storage.save_home(_make_result())
        home_storage.archive_home(home_id)
        home_storage.restore_home(home_id)
        archived = home_storage.list_archived_homes()
        assert not any(h["id"] == home_id for h in archived)


# ── get_oldest_active_home_id ─────────────────────────────────────────────────

class TestOldestActiveHomeId:
    def test_returns_none_when_empty(self):
        assert home_storage.get_oldest_active_home_id() is None

    def test_returns_first_saved_id(self):
        id1 = home_storage.save_home(_make_result(address="First"))
        id2 = home_storage.save_home(_make_result(address="Second"))
        oldest = home_storage.get_oldest_active_home_id()
        assert oldest == id1

    def test_returns_none_when_all_archived(self):
        home_id = home_storage.save_home(_make_result())
        home_storage.archive_home(home_id)
        assert home_storage.get_oldest_active_home_id() is None


# ── list_active_homes ─────────────────────────────────────────────────────────

class TestListActiveHomes:
    def test_empty_by_default(self):
        assert home_storage.list_active_homes() == []

    def test_returns_saved_homes(self):
        home_storage.save_home(_make_result(address="A"))
        home_storage.save_home(_make_result(address="B"))
        active = home_storage.list_active_homes()
        assert len(active) == 2

    def test_does_not_include_archived(self):
        id1 = home_storage.save_home(_make_result(address="A"))
        home_storage.save_home(_make_result(address="B"))
        home_storage.archive_home(id1)
        active = home_storage.list_active_homes()
        assert len(active) == 1
        assert active[0]["address"] == "B"

    def test_session_isolation(self):
        home_storage.save_home(_make_result(address="Session1"))
        _state["nestai_session_id"] = "other-session"
        other_active = home_storage.list_active_homes()
        assert len(other_active) == 0


# ── get_home_by_id ─────────────────────────────────────────────────────────────

class TestGetHomeById:
    def test_returns_home(self):
        home_id = home_storage.save_home(_make_result())
        row = home_storage.get_home_by_id(home_id)
        assert row is not None
        assert row["id"] == home_id

    def test_returns_none_for_missing_id(self):
        assert home_storage.get_home_by_id(99999) is None

    def test_returns_none_for_wrong_session(self):
        home_id = home_storage.save_home(_make_result())
        _state["nestai_session_id"] = "other-session"
        assert home_storage.get_home_by_id(home_id) is None
