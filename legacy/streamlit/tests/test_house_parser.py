"""
Tests for parser/home_listing.py — Zillow house listing parser.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from parser.home_listing import parse_house_listing


# ── Fixtures ──────────────────────────────────────────────────────────────────

SINGLE_LISTING = """
Skip main navigation
Zillow logo
Townhouse for rent
$2,245/mo
Total monthly price

3624 Valley Dr, Alexandria, VA 22302
1
beds

1
baths
805
sqft

Available Sat Aug 15 2026
Cats, dogs OK
In unit laundry

Walk Score®
59
 / 100
Somewhat Walkable

Transit Score®
57
 / 100
Good Transit

Bike Score®
58
 / 100
Bikeable
"""

SEARCH_RESULTS_LISTING = """
Zillow logo

$2,245/mo
Total monthly price

1 bd1 ba805 sqftTownhouse for rent
3624 Valley Dr, Alexandria, VA 22302
More
1 day ago

$3,500/moFees may apply
1 bd1.5 ba962 sqftTownhouse for rent
508 Tobacco Quay, Alexandria, VA 22314
More
4 days ago

$3,600/moFees may apply
3 bds3.5 ba2,114 sqftTownhouse for rent
6267 Alforth Ave, Alexandria, VA 22315
More
"""

COMBINED_LISTING = SINGLE_LISTING + "\n" + SEARCH_RESULTS_LISTING


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestParseHouseListing:
    def test_empty_input_returns_empty(self):
        result = parse_house_listing("")
        assert result["units"] == []
        assert result["unit_count"] == 0
        assert result["property_title"] is None

    def test_whitespace_input_returns_empty(self):
        result = parse_house_listing("   \n\n  ")
        assert result["units"] == []
        assert result["unit_count"] == 0

    def test_single_listing_parses_price(self):
        result = parse_house_listing(SINGLE_LISTING)
        assert result["units"], "Expected at least one unit"
        unit = result["units"][0]
        assert unit["price_num"] == 2245

    def test_single_listing_parses_address(self):
        result = parse_house_listing(SINGLE_LISTING)
        assert "3624 Valley Dr" in result["address"]
        assert "VA 22302" in result["address"]

    def test_single_listing_parses_beds_baths_sqft(self):
        result = parse_house_listing(SINGLE_LISTING)
        unit = result["units"][0]
        assert unit["beds_num"] == 1
        assert unit["baths_num"] == 1.0
        assert unit["sqft_num"] == 805

    def test_single_listing_parses_walk_score(self):
        result = parse_house_listing(SINGLE_LISTING)
        assert result["walk_score"] == 59

    def test_single_listing_parses_transit_score(self):
        result = parse_house_listing(SINGLE_LISTING)
        assert result["transit_score"] == 57

    def test_single_listing_parses_bike_score(self):
        result = parse_house_listing(SINGLE_LISTING)
        assert result["bike_score"] == 58

    def test_single_listing_parses_type(self):
        result = parse_house_listing(SINGLE_LISTING)
        unit = result["units"][0]
        assert unit["type"] is not None
        assert "Townhouse" in unit["type"]

    def test_single_listing_parses_availability(self):
        result = parse_house_listing(SINGLE_LISTING)
        unit = result["units"][0]
        assert unit["availability"] is not None
        assert "Aug" in unit["availability"]

    def test_property_title_derived_from_address(self):
        result = parse_house_listing(SINGLE_LISTING)
        assert result["property_title"] == "3624 Valley Dr"

    def test_search_results_parses_multiple_listings(self):
        result = parse_house_listing(SEARCH_RESULTS_LISTING)
        assert result["unit_count"] >= 3

    def test_search_results_parses_beds_baths_sqft(self):
        result = parse_house_listing(SEARCH_RESULTS_LISTING)
        # First listing: 1 bd, 1 ba, 805 sqft
        first = result["units"][0]
        assert first["beds_num"] == 1
        assert first["baths_num"] == 1.0
        assert first["sqft_num"] == 805

    def test_search_results_parses_fractional_baths(self):
        result = parse_house_listing(SEARCH_RESULTS_LISTING)
        # Second listing: 1.5 ba
        second = result["units"][1]
        assert second["baths_num"] == 1.5

    def test_search_results_parses_comma_sqft(self):
        result = parse_house_listing(SEARCH_RESULTS_LISTING)
        # Third listing: 2,114 sqft
        third = result["units"][2]
        assert third["sqft_num"] == 2114

    def test_combined_no_duplicate_primary(self):
        result = parse_house_listing(COMBINED_LISTING)
        # The primary 3624 Valley Dr address should appear only once
        addresses = [u["address"] for u in result["units"]]
        assert addresses.count("3624 Valley Dr, Alexandria, VA 22302") == 1

    def test_return_structure_keys(self):
        result = parse_house_listing(SINGLE_LISTING)
        for key in ("property_title", "address", "building_nearby", "nearby_places",
                    "building_amenities", "units", "unit_count"):
            assert key in result, f"Missing key: {key}"

    def test_building_nearby_is_empty_dict(self):
        result = parse_house_listing(SINGLE_LISTING)
        assert result["building_nearby"] == {}

    def test_unit_count_matches_units_length(self):
        result = parse_house_listing(COMBINED_LISTING)
        assert result["unit_count"] == len(result["units"])
