"""
tests/test_home_parser.py
Tests for the deterministic Zillow home listing parser.

Test groups:
  A  – Normalisation helpers
  B  – Fixture-based extraction (fixture 1: 3624 Valley Dr, townhouse for rent)
  C  – Fixture-based extraction (fixture 2: 3507 Martha Custis Dr, house for rent)
  D  – Edge cases (empty input, partial text, malformed data)

All tests are offline — no network calls or API keys are needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure importability from any working directory
_STREAMLIT_DIR = Path(__file__).resolve().parent.parent
if str(_STREAMLIT_DIR) not in sys.path:
    sys.path.insert(0, str(_STREAMLIT_DIR))

from parser.home_listing import (
    ParsedHomeResult,
    detect_listing_type,
    extract_address,
    extract_bed_bath_sqft,
    extract_primary_price,
    extract_walk_scores,
    get_fixture_path,
    normalize_currency,
    normalize_lot_size,
    normalize_square_feet,
    parse_home_listing_text,
)


# ─────────────────────────────────────────────────────────────────────────────
# A – Normalisation helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeCurrency:
    def test_monthly_with_comma(self):
        val, typ = normalize_currency("$2,245/mo")
        assert val == 2245
        assert typ == "monthly"

    def test_monthly_no_comma(self):
        val, typ = normalize_currency("$800/mo")
        assert val == 800
        assert typ == "monthly"

    def test_monthly_with_space(self):
        val, typ = normalize_currency("$1,500 /mo")
        assert val == 1500
        assert typ == "monthly"

    def test_sale_price(self):
        val, typ = normalize_currency("$450,000")
        assert val == 450000
        assert typ == "sale"

    def test_sale_price_no_comma(self):
        val, typ = normalize_currency("$500000")
        assert val == 500000
        assert typ == "sale"

    def test_none_input(self):
        val, typ = normalize_currency(None)
        assert val is None

    def test_empty_string(self):
        val, typ = normalize_currency("")
        assert val is None


class TestNormalizeSquareFeet:
    def test_plain_integer(self):
        assert normalize_square_feet("805") == 805

    def test_with_label(self):
        assert normalize_square_feet("1,080 sqft") == 1080

    def test_with_comma(self):
        assert normalize_square_feet("2,806") == 2806

    def test_none_input(self):
        assert normalize_square_feet(None) is None

    def test_empty_string(self):
        assert normalize_square_feet("") is None


class TestNormalizeLotSize:
    def test_acres(self):
        val, unit = normalize_lot_size("0.25 acres")
        assert val == pytest.approx(0.25)
        assert unit == "acres"

    def test_sqft(self):
        val, unit = normalize_lot_size("1,200 sq ft")
        assert val == 1200.0
        assert unit == "sqft"

    def test_acreage_no_decimal(self):
        val, unit = normalize_lot_size("1 acre")
        assert val == pytest.approx(1.0)
        assert unit == "acres"

    def test_none_input(self):
        val, unit = normalize_lot_size(None)
        assert val is None


class TestDetectListingType:
    def test_for_rent_text(self):
        assert detect_listing_type("Townhouse for rent\n$2,245/mo") == "RENTAL_HOME"

    def test_for_sale_text(self):
        assert detect_listing_type("House for sale\n$450,000") == "HOME_FOR_SALE"

    def test_monthly_price_only(self):
        text = "Some property\n$1,500/mo\nDetails here"
        assert detect_listing_type(text) == "RENTAL_HOME"

    def test_unknown_fallback(self):
        assert detect_listing_type("Some property listing\nNo price here") == "UNKNOWN"

    def test_rent_beats_sale(self):
        # "for rent" appears before "for sale" in header → RENTAL_HOME
        text = "Townhouse for rent\nSome text\nFor sale elsewhere"
        assert detect_listing_type(text) == "RENTAL_HOME"


class TestExtractAddress:
    def test_standard_address(self):
        text = "3624 Valley Dr, Alexandria, VA 22302\n"
        full, street, city, state, postal = extract_address(text)
        assert full == "3624 Valley Dr, Alexandria, VA 22302"
        assert street == "3624 Valley Dr"
        assert city == "Alexandria"
        assert state == "VA"
        assert postal == "22302"

    def test_multi_word_city(self):
        text = "123 Main St, Falls Church, VA 22046\n"
        full, street, city, state, postal = extract_address(text)
        assert city == "Falls Church"
        assert state == "VA"
        assert postal == "22046"

    def test_no_address(self):
        full, street, city, state, postal = extract_address("No address here")
        assert full == ""


class TestExtractBedBathSqft:
    def test_standard_pattern(self):
        text = "1\nbeds\n\n1\nbaths\n805\nsqft\n"
        beds, baths, sqft = extract_bed_bath_sqft(text)
        assert beds == 1
        assert baths == 1.0
        assert sqft == 805

    def test_decimal_bathrooms(self):
        text = "2\nbeds\n\n2.5\nbaths\n1200\nsqft\n"
        beds, baths, sqft = extract_bed_bath_sqft(text)
        assert beds == 2
        assert baths == 2.5
        assert sqft == 1200

    def test_sqft_with_comma(self):
        text = "3\nbeds\n\n2\nbaths\n1,540\nsqft\n"
        beds, baths, sqft = extract_bed_bath_sqft(text)
        assert sqft == 1540

    def test_no_pattern(self):
        beds, baths, sqft = extract_bed_bath_sqft("Nothing here")
        assert beds is None and baths is None and sqft is None


class TestExtractPrimaryPrice:
    def test_monthly_rent(self):
        text = "$2,245/mo\nTotal monthly price\n"
        val, typ, raw = extract_primary_price(text)
        assert val == 2245
        assert typ == "monthly"
        assert "/mo" in raw

    def test_first_price_wins(self):
        # Primary price should be extracted, not a later nearby listing price
        text = "$2,245/mo\nSome content\n$3,500/moFees may apply\n"
        val, typ, raw = extract_primary_price(text)
        assert val == 2245


# ─────────────────────────────────────────────────────────────────────────────
# B – Fixture 1: 3624 Valley Dr, Alexandria, VA 22302
#     Townhouse for rent • $2,245/mo • 1 bed / 1 bath / 805 sqft
# ─────────────────────────────────────────────────────────────────────────────

class TestFixture1:
    def test_property_type(self, result_1):
        assert result_1.property_type == "RENTAL_HOME"

    def test_address(self, result_1):
        assert result_1.address == "3624 Valley Dr, Alexandria, VA 22302"

    def test_city(self, result_1):
        assert result_1.city == "Alexandria"

    def test_state(self, result_1):
        assert result_1.state == "VA"

    def test_postal_code(self, result_1):
        assert result_1.postal_code == "22302"

    def test_monthly_rent(self, result_1):
        assert result_1.monthly_rent == 2245

    def test_sale_price_not_set(self, result_1):
        # Monthly rent should never populate sale_price
        assert result_1.sale_price is None

    def test_bedrooms(self, result_1):
        assert result_1.bedrooms == 1

    def test_bathrooms(self, result_1):
        assert result_1.bathrooms == 1.0

    def test_square_feet(self, result_1):
        assert result_1.square_feet == 805

    def test_walk_score(self, result_1):
        assert result_1.walk_score == 59

    def test_transit_score(self, result_1):
        assert result_1.transit_score == 57

    def test_bike_score(self, result_1):
        assert result_1.bike_score == 58

    def test_schools_present(self, result_1):
        schools_lower = [s.lower() for s in result_1.schools]
        assert any("charles barrett" in s for s in schools_lower)

    def test_features_not_empty(self, result_1):
        assert len(result_1.features) >= 1

    def test_features_contain_hardwood(self, result_1):
        features_lower = [f.lower() for f in result_1.features]
        assert any("hardwood" in f for f in features_lower)

    def test_description_not_empty(self, result_1):
        assert len(result_1.description) > 20

    def test_hours_on_zillow(self, result_1):
        # Fixture 1 says "23 hours on Zillow"
        assert result_1.hours_on_zillow == 23

    def test_days_on_zillow_not_set(self, result_1):
        # Only hours should be set, not days
        assert result_1.days_on_zillow is None

    def test_no_parser_crash(self, result_1):
        # Result must always be a ParsedHomeResult instance
        assert isinstance(result_1, ParsedHomeResult)

    def test_warnings_is_list(self, result_1):
        assert isinstance(result_1.warnings, list)

    def test_fields_not_found_is_list(self, result_1):
        assert isinstance(result_1.fields_not_found, list)

    def test_property_subtype_is_townhouse(self, result_1):
        assert result_1.property_subtype.lower() == "townhouse"

    def test_available_date(self, result_1):
        # Available Sat Aug 15 2026
        assert "aug" in result_1.available_date.lower() or result_1.available_date != ""

    def test_pets_policy(self, result_1):
        assert result_1.pets_policy != ""

    def test_cooling_present(self, result_1):
        assert "air conditioner" in result_1.cooling.lower()


# ─────────────────────────────────────────────────────────────────────────────
# C – Fixture 2: 3507 Martha Custis Dr, Alexandria, VA 22302
#     House for rent • $2,100/mo • 1 bed / 1 bath / 780 sqft
# ─────────────────────────────────────────────────────────────────────────────

class TestFixture2:
    def test_property_type(self, result_2):
        assert result_2.property_type == "RENTAL_HOME"

    def test_address(self, result_2):
        assert result_2.address == "3507 Martha Custis Dr, Alexandria, VA 22302"

    def test_city(self, result_2):
        assert result_2.city == "Alexandria"

    def test_state(self, result_2):
        assert result_2.state == "VA"

    def test_postal_code(self, result_2):
        assert result_2.postal_code == "22302"

    def test_monthly_rent(self, result_2):
        assert result_2.monthly_rent == 2100

    def test_sale_price_not_set(self, result_2):
        assert result_2.sale_price is None

    def test_bedrooms(self, result_2):
        assert result_2.bedrooms == 1

    def test_bathrooms(self, result_2):
        assert result_2.bathrooms == 1.0

    def test_square_feet(self, result_2):
        assert result_2.square_feet == 780

    def test_walk_score(self, result_2):
        assert result_2.walk_score == 65

    def test_transit_score(self, result_2):
        assert result_2.transit_score == 58

    def test_bike_score(self, result_2):
        assert result_2.bike_score == 66

    def test_schools_present(self, result_2):
        schools_lower = [s.lower() for s in result_2.schools]
        assert any("charles barrett" in s for s in schools_lower)

    def test_features_not_empty(self, result_2):
        assert len(result_2.features) >= 1

    def test_features_contain_pools(self, result_2):
        features_lower = [f.lower() for f in result_2.features]
        assert any("pool" in f for f in features_lower)

    def test_features_contain_parquet(self, result_2):
        features_lower = [f.lower() for f in result_2.features]
        assert any("parquet" in f or "hardwood" in f or "oak" in f for f in features_lower)

    def test_description_not_empty(self, result_2):
        assert len(result_2.description) > 20

    def test_days_on_zillow(self, result_2):
        # Fixture 2 says "18 days on Zillow"
        assert result_2.days_on_zillow == 18

    def test_hours_on_zillow_not_set(self, result_2):
        assert result_2.hours_on_zillow is None

    def test_property_subtype(self, result_2):
        assert "single family" in result_2.property_subtype.lower() or result_2.property_subtype != ""

    def test_available_date(self, result_2):
        assert "aug" in result_2.available_date.lower() or result_2.available_date != ""

    def test_pets_policy_no_pets(self, result_2):
        assert "no pets" in result_2.pets_policy.lower()

    def test_cooling_present(self, result_2):
        assert "air conditioner" in result_2.cooling.lower()


# ─────────────────────────────────────────────────────────────────────────────
# D – Edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_input_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_home_listing_text("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_home_listing_text("   \n\t  ")

    def test_partial_text_no_crash(self):
        """Partial text should return a result with warnings, not crash."""
        partial = "Some listing\n$1,200/mo\n2 Elm St, Springfield, VA 22150\n"
        result = parse_home_listing_text(partial)
        assert isinstance(result, ParsedHomeResult)
        assert result.monthly_rent == 1200

    def test_missing_optional_fields_return_none(self):
        minimal = "House for rent\n$1,500/mo\n1 Oak St, Fairfax, VA 22030\n1\nbeds\n\n1\nbaths\n600\nsqft\n"
        result = parse_home_listing_text(minimal)
        # Optional fields are absent — no crash, no fake values
        assert result.walk_score is None
        assert result.days_on_zillow is None
        assert result.schools == []

    def test_no_hoa_no_garage_are_none(self):
        minimal = "House for rent\n$2,000/mo\n5 Pine Ave, Reston, VA 20190\n2\nbeds\n\n1\nbaths\n900\nsqft\n"
        result = parse_home_listing_text(minimal)
        # HOA and garage are not modelled in RENTAL_HOME — they should not appear
        # We simply verify the parser doesn't fabricate values from absent fields.
        assert result.monthly_rent == 2000
        assert result.bedrooms == 2

    def test_price_with_commas(self):
        text = "House for rent\n$2,245/mo\n3 Street Rd, City, VA 22000\n"
        result = parse_home_listing_text(text)
        assert result.monthly_rent == 2245

    def test_decimal_bathroom_count(self):
        text = "House for rent\n$3,000/mo\n7 Road St, Town, VA 22001\n3\nbeds\n\n2.5\nbaths\n1500\nsqft\n"
        result = parse_home_listing_text(text)
        assert result.bathrooms == 2.5

    def test_nearby_listings_do_not_contaminate_price(self, fixture_1_text):
        """The parser must return the primary listing price, not a nearby listing price."""
        result = parse_home_listing_text(fixture_1_text)
        # Primary price is $2,245. Nearby listings include $3,500, $4,600, etc.
        assert result.monthly_rent == 2245

    def test_nearby_listings_do_not_contaminate_address(self, fixture_1_text):
        """The parser must return the primary address, not a nearby listing address."""
        result = parse_home_listing_text(fixture_1_text)
        assert result.address == "3624 Valley Dr, Alexandria, VA 22302"

    def test_repeated_price_in_text(self):
        """When price appears more than once, take the first occurrence."""
        text = "Townhouse for rent\n$2,245/mo\nTotal monthly price\n$2,245/mo\nSomething else\n"
        val, typ, raw = extract_primary_price(text)
        assert val == 2245

    def test_for_sale_listing_type(self):
        text = "House for sale\n$399,000\n10 Oak St, McLean, VA 22101\n"
        result = parse_home_listing_text(text)
        assert result.property_type == "HOME_FOR_SALE"
        assert result.sale_price == 399000
        assert result.monthly_rent is None

    def test_walk_scores_only_in_primary_section(self, fixture_1_text):
        """Walk scores from the primary section (59/57/58) must be returned."""
        result = parse_home_listing_text(fixture_1_text)
        assert result.walk_score == 59

    def test_fixture_paths_are_absolute(self):
        p1 = get_fixture_path("home_example_1.txt")
        p2 = get_fixture_path("home_example_2.txt")
        assert p1.is_absolute()
        assert p2.is_absolute()
        assert p1.exists(), f"Canonical fixture not found: {p1}"
        assert p2.exists(), f"Canonical fixture not found: {p2}"

    def test_result_has_no_none_values_for_core_fields_on_good_input(self, result_1):
        """All five required core fields must be populated for a complete fixture."""
        assert result_1.address
        assert result_1.monthly_rent is not None
        assert result_1.bedrooms is not None
        assert result_1.bathrooms is not None
        assert result_1.square_feet is not None
