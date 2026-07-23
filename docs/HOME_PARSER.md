# NestAI Zillow Home Parser

## Overview

`legacy/streamlit/parser/home_listing.py` provides a **deterministic, no-network** Zillow pasted-text parser.

It extracts structured data from text copied from a Zillow listing page (Ctrl+A, Ctrl+C).  
No LLM, no network call, no external dependency.

---

## Entry Point

```python
from parser.home_listing import parse_home_listing_text, ParsedHomeResult

result: ParsedHomeResult = parse_home_listing_text(text)
```

---

## ParsedHomeResult Fields

| Field | Type | Description |
|---|---|---|
| `property_type` | `str` | `RENTAL_HOME` or `HOME_FOR_SALE` |
| `property_subtype` | `str \| None` | e.g., `Townhouse`, `House` |
| `address` | `str \| None` | Full address string |
| `street` | `str \| None` | Street address only |
| `city` | `str \| None` | City |
| `state` | `str \| None` | State abbreviation |
| `postal_code` | `str \| None` | ZIP code |
| `display_name` | `str \| None` | Short display label |
| `monthly_rent` | `int \| None` | Monthly rent in dollars (rentals) |
| `sale_price` | `int \| None` | Purchase price (for-sale) |
| `price_raw` | `str \| None` | Raw price string from source |
| `bedrooms` | `int \| None` | Number of bedrooms |
| `bathrooms` | `float \| None` | Number of bathrooms |
| `square_feet` | `int \| None` | Interior square footage |
| `available_date` | `str \| None` | Availability date text |
| `pets_policy` | `str \| None` | Pets policy text |
| `security_deposit` | `int \| None` | Security deposit |
| `application_fee` | `int \| None` | Application fee |
| `cooling` | `str \| None` | Cooling system description |
| `heating` | `str \| None` | Heating system description |
| `parking` | `str \| None` | Parking description |
| `laundry` | `str \| None` | Laundry description |
| `walk_score` | `int \| None` | Walk Score (0–100) |
| `transit_score` | `int \| None` | Transit Score (0–100) |
| `bike_score` | `int \| None` | Bike Score (0–100) |
| `walk_description` | `str \| None` | Walk Score label (e.g., "Bikeable") |
| `transit_description` | `str \| None` | Transit label |
| `bike_description` | `str \| None` | Bike label |
| `days_on_zillow` | `int \| None` | Days on Zillow |
| `hours_on_zillow` | `int \| None` | Hours on Zillow (< 1 day) |
| `listing_updated` | `str \| None` | "Updated X days ago" text |
| `description` | `str \| None` | Full description text |
| `features` | `list[str]` | "What's special" bullet features |
| `schools` | `list[str]` | School names near the listing |
| `warnings` | `list[str]` | Parse warnings |
| `fields_not_found` | `list[str]` | Fields that were not extracted |

---

## Listing Type Detection

The parser classifies listings as `RENTAL_HOME` or `HOME_FOR_SALE`:

- Checks the first 40 lines for "for rent" → `RENTAL_HOME`
- Checks the first 40 lines for "for sale" → `HOME_FOR_SALE`
- Falls back to price format: `$X/mo` → `RENTAL_HOME`, plain `$X` → `HOME_FOR_SALE`

---

## Fixture Files (Canonical Paths)

Both Zillow examples are stored at canonical paths relative to `legacy/streamlit/data/`:

| File | Address | Type | Price |
|---|---|---|---|
| `data/home_example_1.txt` | 3624 Valley Dr, Alexandria VA 22302 | `RENTAL_HOME` | $2,245/mo |
| `data/home_example_2.txt` | 3507 Martha Custis Dr, Alexandria VA 22302 | `RENTAL_HOME` | $2,100/mo |

Load them in tests via:

```python
from parser.home_listing import get_fixture_path
text = get_fixture_path("home_example_1.txt").read_text(encoding="utf-8")
```

This helper uses `Path(__file__).resolve()` so it works regardless of the current working directory.

---

## Design Decisions

- **Primary section isolation**: The parser cuts the input at the first occurrence of "Request a tour" before extracting fields, preventing nearby-listing search results from contaminating the parse.
- **Price**: Takes the FIRST `$X/mo` or `$X` match in the primary section.
- **Beds/baths/sqft**: Each on its own line, followed by the label on the next line.
- **Features**: Short lines (≤60 chars) before the first long description line.
- **Scores**: Extracted from `Walk Score®`, `Transit Score®`, `Bike Score®` pattern.
- **Schools**: Lines that end in `Elementary`, `Middle`, `High`, `School`, `Academy`, or `Preschool`.

---

## Tests

```bash
cd legacy/streamlit
python -m pytest tests/test_home_parser.py -v
```

94 tests covering: currency normalization, sqft/lot normalization, listing type detection, address extraction, beds/baths/sqft extraction, price extraction, and full fixture parsing.
