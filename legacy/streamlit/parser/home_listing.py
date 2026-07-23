"""
parser/home_listing.py
Deterministic Zillow rental/sale listing text parser.

Supports two property types derived from listing language and price format:
  - RENTAL_HOME  : "for rent" / "$X/mo" price → monthly_rent field
  - HOME_FOR_SALE: "for sale" / bare purchase price → sale_price field

Usage::

    from parser.home_listing import parse_home_listing_text, get_fixture_path
    text = get_fixture_path("home_example_1.txt").read_text(encoding="utf-8")
    result = parse_home_listing_text(text)
    # result.property_type == "RENTAL_HOME"
    # result.monthly_rent == 2245

NOTE (local/session-based enforcement):
    This module contains no network calls and no external API dependencies.
    All parsing is deterministic and can be run without API keys.
    Ownership and quota enforcement is the responsibility of the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── Canonical fixture path helper ─────────────────────────────────────────────

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def get_fixture_path(name: str) -> Path:
    """Return the absolute path to a canonical data fixture file.

    The returned path is always relative to the parser's own data directory,
    so it works regardless of the current working directory.
    """
    return _DATA_DIR / name


# ── Parse result ──────────────────────────────────────────────────────────────

@dataclass
class ParsedHomeResult:
    """Structured result from :func:`parse_home_listing_text`.

    All fields have safe defaults so callers can always access any attribute
    without checking whether parsing succeeded.  Consult ``warnings`` and
    ``fields_not_found`` to understand extraction confidence.
    """

    # ── Listing identity ──────────────────────────────────────────────────────
    property_type: str = ""       # "RENTAL_HOME" | "HOME_FOR_SALE" | "UNKNOWN"
    property_subtype: str = ""    # "Townhouse" | "Single family residence" | …
    address: str = ""             # full address string, e.g. "3624 Valley Dr, Alexandria, VA 22302"
    street: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    display_name: str = ""        # populated from address or title

    # ── Price ─────────────────────────────────────────────────────────────────
    monthly_rent: Optional[int] = None    # RENTAL_HOME: dollars/month
    sale_price: Optional[int] = None      # HOME_FOR_SALE: purchase price
    price_raw: str = ""                   # original extracted price string

    # ── Size ──────────────────────────────────────────────────────────────────
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None
    square_feet: Optional[int] = None

    # ── Rental-specific details ───────────────────────────────────────────────
    available_date: str = ""
    pets_policy: str = ""
    security_deposit: Optional[int] = None
    application_fee: Optional[int] = None

    # ── Home facts ────────────────────────────────────────────────────────────
    cooling: str = ""
    heating: str = ""
    parking: str = ""
    laundry: str = ""

    # ── Walkability scores (from primary listing section, not search results) ─
    walk_score: Optional[int] = None
    transit_score: Optional[int] = None
    bike_score: Optional[int] = None
    walk_description: str = ""
    transit_description: str = ""
    bike_description: str = ""

    # ── Listing lifecycle ─────────────────────────────────────────────────────
    days_on_zillow: Optional[int] = None
    hours_on_zillow: Optional[int] = None  # set when listing is < 24 h old
    listing_updated: str = ""

    # ── Content ───────────────────────────────────────────────────────────────
    description: str = ""
    features: list = field(default_factory=list)   # "What's special" bullet items
    schools: list = field(default_factory=list)    # school name strings

    # ── Extraction metadata ───────────────────────────────────────────────────
    warnings: list = field(default_factory=list)
    fields_not_found: list = field(default_factory=list)


# ── Normalisation helpers ─────────────────────────────────────────────────────

def normalize_currency(value: str) -> tuple[Optional[int], str]:
    """Return (numeric_value, price_type) for a raw price string.

    ``price_type`` is ``"monthly"`` when the string contains ``/mo`` or
    ``"monthly rent"``, and ``"sale"`` otherwise.

    Examples::

        normalize_currency("$2,245/mo")  # (2245, "monthly")
        normalize_currency("$450,000")   # (450000, "sale")
        normalize_currency("$2,245")     # (2245, "sale")
    """
    if not value or not isinstance(value, str):
        return None, "unknown"
    is_monthly = bool(re.search(r'/\s*mo(?:nth)?', value, re.IGNORECASE))
    m = re.search(r'\$?([\d,]+)', value.replace(" ", ""))
    if not m:
        return None, "monthly" if is_monthly else "sale"
    numeric = int(m.group(1).replace(",", ""))
    return numeric, "monthly" if is_monthly else "sale"


def normalize_square_feet(value: str) -> Optional[int]:
    """Return square footage as an integer, or None if unparseable.

    Handles commas and trailing unit labels::

        normalize_square_feet("805")         # 805
        normalize_square_feet("1,080 sqft")  # 1080
    """
    if not value or not isinstance(value, str):
        return None
    m = re.search(r'([\d,]+)', value.replace(" ", ""))
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def normalize_lot_size(value: str) -> tuple[Optional[float], str]:
    """Return (numeric_size, unit) where unit is ``"acres"`` or ``"sqft"``.

    Examples::

        normalize_lot_size("0.25 acres") # (0.25, "acres")
        normalize_lot_size("1,200 sq ft") # (1200.0, "sqft")
    """
    if not value or not isinstance(value, str):
        return None, ""
    if re.search(r'\bacres?\b', value, re.IGNORECASE):
        m = re.search(r'([\d.]+)', value)
        return (float(m.group(1)) if m else None), "acres"
    m = re.search(r'([\d,]+)', value)
    return (float(m.group(1).replace(",", "")) if m else None), "sqft"


# ── Primary section extraction ─────────────────────────────────────────────────

_PRIMARY_STOP_PATTERNS = [
    r"^Request a tour\s*$",
    r"^Virginia[A-Z]",            # breadcrumb like "VirginiaAlexandria City..."
    r"^Related Searches\s*$",
    r"^Nearby cities\s*$",
    r"^Apply now\s*$",
]


def _extract_primary_section(text: str) -> str:
    """Return the primary listing section, stripping navigation and search results.

    The Zillow pasted text contains two logical parts:
    1. The primary listing detail (price, address, facts, description, scores).
    2. A Zillow search-results panel and site navigation appended below.

    This function isolates part 1 by finding the first reliable stop marker.
    """
    lines = text.splitlines()
    stop_re = [re.compile(p, re.IGNORECASE) for p in _PRIMARY_STOP_PATTERNS]
    cutoff = len(lines)
    for i, line in enumerate(lines):
        for pat in stop_re:
            if pat.search(line):
                cutoff = i
                break
        else:
            continue
        break
    return "\n".join(lines[:cutoff])


# ── Listing type detection ─────────────────────────────────────────────────────

def detect_listing_type(text: str) -> str:
    """Classify text as ``"RENTAL_HOME"``, ``"HOME_FOR_SALE"``, or ``"UNKNOWN"``.

    Decision criteria (in order):
    1. First 40 lines contain ``"for rent"`` → RENTAL_HOME.
    2. First 40 lines contain ``"for sale"`` → HOME_FOR_SALE.
    3. Price in first 500 characters uses ``/mo`` → RENTAL_HOME.
    4. Falls back to UNKNOWN.
    """
    header = "\n".join(text.splitlines()[:40])
    if re.search(r'\bfor\s+rent\b', header, re.IGNORECASE):
        return "RENTAL_HOME"
    if re.search(r'\bfor\s+sale\b', header, re.IGNORECASE):
        return "HOME_FOR_SALE"
    if re.search(r'\$[\d,]+\s*/\s*mo', text[:500], re.IGNORECASE):
        return "RENTAL_HOME"
    return "UNKNOWN"


# ── Field extractors ──────────────────────────────────────────────────────────

def extract_address(text: str) -> tuple[str, str, str, str, str]:
    """Return (full_address, street, city, state, zip) from the first address match.

    Matches patterns like ``3624 Valley Dr, Alexandria, VA 22302``.
    Returns empty strings for any component that cannot be parsed.
    """
    pat = re.compile(
        r'^([A-Z0-9][^,\n]{2,60}),\s*'   # street
        r'([A-Za-z][^,\n]{1,40}),\s*'    # city
        r'([A-Z]{2})\s+'                  # state
        r'(\d{5})\b',                     # zip
        re.MULTILINE,
    )
    m = pat.search(text)
    if not m:
        return "", "", "", "", ""
    street = m.group(1).strip()
    city = m.group(2).strip()
    state = m.group(3).strip()
    postal = m.group(4).strip()
    full = f"{street}, {city}, {state} {postal}"
    return full, street, city, state, postal


def extract_primary_price(text: str) -> tuple[Optional[int], str, str]:
    """Return (numeric_price, price_type, raw_string) for the primary listing price.

    For rental listings the first ``$X/mo`` match is used.
    For sale listings the first bare ``$X`` (large integer > 10 000) is used.
    Returns ``(None, "", "")`` if no price is found.
    """
    # Prefer monthly rent pattern
    m = re.search(r'\$([\d,]+)\s*/\s*mo', text, re.IGNORECASE)
    if m:
        raw = m.group(0)
        val = int(m.group(1).replace(",", ""))
        return val, "monthly", raw
    # Fall back to large bare price (sale)
    m = re.search(r'\$([\d,]{6,})\b', text)
    if m:
        raw = m.group(0)
        val = int(m.group(1).replace(",", ""))
        return val, "sale", raw
    return None, "", ""


def extract_bed_bath_sqft(text: str) -> tuple[Optional[int], Optional[float], Optional[int]]:
    """Return (bedrooms, bathrooms, square_feet) from the primary listing block.

    Matches the Zillow pasted-text pattern where each value appears on its own
    line immediately before its label::

        1
        beds

        1
        baths
        805
        sqft
    """
    m = re.search(
        r'(\d+)\s*\n\s*beds?\s*\n[\s\n]*'
        r'(\d+(?:\.\d+)?)\s*\n\s*baths?\s*\n\s*'
        r'(\d[\d,]*)\s*\n\s*sqft',
        text,
        re.IGNORECASE,
    )
    if m:
        beds = int(m.group(1))
        baths = float(m.group(2))
        sqft = int(m.group(3).replace(",", ""))
        return beds, baths, sqft
    return None, None, None


def extract_home_facts(text: str) -> dict:
    """Extract property subtype, availability, pets, cooling, laundry, parking, heating.

    Looks for the property-info block that appears between the sqft line and
    ``What's special`` in Zillow pasted text.
    """
    facts: dict[str, str] = {
        "property_subtype": "",
        "available_date": "",
        "pets_policy": "",
        "cooling": "",
        "laundry": "",
        "parking": "",
        "heating": "",
        "security_deposit": "",
        "application_fee": "",
    }

    # Narrow to the info block (between sqft and What's special)
    info_m = re.search(
        r'sqft\s*\n(.*?)(?:What\'s special|Show more)',
        text,
        re.DOTALL | re.IGNORECASE,
    )
    section = info_m.group(1) if info_m else text

    lines = [l.strip() for l in section.splitlines() if l.strip()]

    # Known noise strings to skip
    noise_re = re.compile(
        r'(This listing|Price may|Learn more|Cost calculator|Fast &|This property|'
        r'Apply now|Security deposit|Pet fee|Application|All pricing|'
        r'Est\.|Based on|Required|Optional|Move-in)',
        re.IGNORECASE,
    )

    _HEATING_TERMS = {
        "central", "baseboard", "forced air", "heat pump", "electric",
        "radiant", "gas", "steam", "wall heater", "mini-split",
    }

    for line in lines:
        if noise_re.search(line):
            continue
        # Skip lines that are only punctuation / single characters
        if len(line) <= 1:
            continue
        if re.match(r'^[|/\\•·–—]+$', line):
            continue
        lc = line.lower()

        if re.match(r'^available\b', line, re.I):
            facts["available_date"] = line
        elif re.match(r'^(no pets|cats|dogs|pets|pet-friendly)', line, re.I):
            facts["pets_policy"] = line
        elif re.match(r'^air conditioner', line, re.I):
            facts["cooling"] = line
        elif re.search(r'\blaundry\b', line, re.I):
            facts["laundry"] = line
        elif re.search(r'\bparking\b', line, re.I):
            facts["parking"] = line
        elif lc in _HEATING_TERMS and not facts["heating"]:
            facts["heating"] = line
        elif not facts["property_subtype"] and len(line) < 60 and line:
            facts["property_subtype"] = line

    # Security deposit and application fee from full text
    dep_m = re.search(r'Security deposit\s*\n\s*\$?([\d,]+)', text, re.IGNORECASE)
    if dep_m:
        facts["security_deposit"] = dep_m.group(1).replace(",", "")
    app_m = re.search(r'Administration fee\s*\n\s*\$?([\d,]+)', text, re.IGNORECASE)
    if not app_m:
        app_m = re.search(r'\$([\d,]+)\s+application fee', text, re.IGNORECASE)
    if app_m:
        facts["application_fee"] = app_m.group(1).replace(",", "")

    return facts


def extract_description(text: str) -> tuple[list, str]:
    """Return (feature_list, description_text) from the ``What's special`` section.

    Feature items are the short lines (≤ 60 chars) that immediately follow
    ``What's special`` before the longer description paragraphs begin.
    """
    m = re.search(
        r"What's special\s*\n(.*?)(?:Show more\s*\n|(?:\d+\s+(?:hours?|days?)\s*\n\s*on Zillow))",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        # Fallback: try to find description without "Show more" boundary
        m = re.search(r"What's special\s*\n(.{10,2000})", text, re.DOTALL | re.IGNORECASE)
    if not m:
        return [], ""

    section = m.group(1)
    raw_lines = section.splitlines()

    features: list[str] = []
    desc_lines: list[str] = []
    in_description = False

    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        if not in_description:
            if len(line) <= 60:
                features.append(line)
            else:
                in_description = True
                desc_lines.append(line)
        else:
            desc_lines.append(line)

    description = " ".join(desc_lines).strip()
    return _dedup_list(features), description


def extract_walk_scores(text: str) -> tuple[Optional[int], Optional[int], Optional[int], str, str, str]:
    """Return (walk, transit, bike, walk_desc, transit_desc, bike_desc)."""

    def _score_and_desc(label: str) -> tuple[Optional[int], str]:
        pat = re.compile(
            rf'{re.escape(label)}[\u00ae]?\s*\n\s*(\d+)\s*\n\s*/\s*100\s*\n\s*([^\n]+)',
            re.IGNORECASE,
        )
        m = pat.search(text)
        if m:
            score = int(m.group(1))
            if 0 <= score <= 100:
                return score, m.group(2).strip()
        return None, ""

    walk, walk_d = _score_and_desc("Walk Score")
    transit, transit_d = _score_and_desc("Transit Score")
    bike, bike_d = _score_and_desc("Bike Score")
    return walk, transit, bike, walk_d, transit_d, bike_d


def extract_school_information(text: str) -> list[str]:
    """Return a list of school name strings from the ``Nearby schools`` section."""
    m = re.search(
        r'Nearby schools\b(.*?)(?:More school details|Cost calculator)',
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return []

    _SKIP = re.compile(
        r'^(Grades|Source:|GreatSchools|Test Score|Student Progress|College Readiness|'
        r'N/A|/10|\d+/10|\d+$|• [\d.]+|Show)',
        re.IGNORECASE,
    )

    schools: list[str] = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or _SKIP.search(line):
            continue
        if re.match(r'^[\d.]+$', line):
            continue
        schools.append(line)
    return _dedup_list(schools)


def extract_days_on_zillow(text: str) -> tuple[Optional[int], Optional[int], str]:
    """Return (days, hours, listing_updated_string).

    ``days`` is set when the listing shows ``N days on Zillow``.
    ``hours`` is set when the listing shows ``N hours on Zillow``.
    Only one of the two is non-None for a given listing.
    """
    days: Optional[int] = None
    hours: Optional[int] = None
    updated = ""

    days_m = re.search(r'(\d+)\s+days?\s*\n\s*on\s+Zillow', text, re.IGNORECASE)
    if days_m:
        days = int(days_m.group(1))

    hours_m = re.search(r'(\d+)\s+hours?\s*\n\s*on\s+Zillow', text, re.IGNORECASE)
    if hours_m:
        hours = int(hours_m.group(1))

    upd_m = re.search(r'Listing updated:\s*([^\n]+)', text, re.IGNORECASE)
    if upd_m:
        updated = upd_m.group(1).strip()

    return days, hours, updated


# ── Internal helpers ──────────────────────────────────────────────────────────

def _dedup_list(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


# ── Main entry point ──────────────────────────────────────────────────────────

_MAX_RAW_TEXT_BYTES = 128_000   # ~128 KB cap on stored raw text


def parse_home_listing_text(text: str) -> ParsedHomeResult:
    """Parse pasted Zillow listing text into a :class:`ParsedHomeResult`.

    This function is deterministic and requires no network calls or API keys.
    It handles malformed or partial text gracefully: missing optional fields
    are recorded in ``result.fields_not_found`` and ``result.warnings``
    rather than raising exceptions.

    Raises:
        ValueError: if ``text`` is empty or contains only whitespace.
    """
    if not text or not text.strip():
        raise ValueError("Input text is empty or whitespace-only")

    result = ParsedHomeResult()

    # ── Isolate primary listing block ─────────────────────────────────────────
    primary = _extract_primary_section(text)

    # ── Listing type ──────────────────────────────────────────────────────────
    result.property_type = detect_listing_type(primary)
    if result.property_type == "UNKNOWN":
        result.warnings.append("Could not determine property type (RENTAL_HOME or HOME_FOR_SALE)")

    # ── Address ───────────────────────────────────────────────────────────────
    full, street, city, state, postal = extract_address(primary)
    if full:
        result.address = full
        result.street = street
        result.city = city
        result.state = state
        result.postal_code = postal
        result.display_name = full
    else:
        result.fields_not_found.append("address")
        result.warnings.append("Could not extract a full address")

    # ── Price ─────────────────────────────────────────────────────────────────
    price_val, price_type, price_raw = extract_primary_price(primary)
    result.price_raw = price_raw
    if price_val is not None:
        if price_type == "monthly" or result.property_type == "RENTAL_HOME":
            result.monthly_rent = price_val
        else:
            result.sale_price = price_val
    else:
        result.fields_not_found.append("price")
        result.warnings.append("Could not extract listing price")

    # ── Beds / baths / sqft ───────────────────────────────────────────────────
    beds, baths, sqft = extract_bed_bath_sqft(primary)
    result.bedrooms = beds
    result.bathrooms = baths
    result.square_feet = sqft
    for name, val in (("bedrooms", beds), ("bathrooms", baths), ("square_feet", sqft)):
        if val is None:
            result.fields_not_found.append(name)

    # ── Home facts ────────────────────────────────────────────────────────────
    facts = extract_home_facts(primary)
    result.property_subtype = facts["property_subtype"]
    result.available_date = facts["available_date"]
    result.pets_policy = facts["pets_policy"]
    result.cooling = facts["cooling"]
    result.heating = facts["heating"]
    result.laundry = facts["laundry"]
    result.parking = facts["parking"]
    if facts.get("security_deposit"):
        try:
            result.security_deposit = int(facts["security_deposit"])
        except (ValueError, TypeError):
            pass
    if facts.get("application_fee"):
        try:
            result.application_fee = int(facts["application_fee"])
        except (ValueError, TypeError):
            pass

    # ── Features and description ──────────────────────────────────────────────
    result.features, result.description = extract_description(primary)

    # ── Walk / transit / bike scores ──────────────────────────────────────────
    walk, transit, bike, wdesc, tdesc, bdesc = extract_walk_scores(primary)
    result.walk_score = walk
    result.transit_score = transit
    result.bike_score = bike
    result.walk_description = wdesc
    result.transit_description = tdesc
    result.bike_description = bdesc

    # ── Schools ───────────────────────────────────────────────────────────────
    result.schools = extract_school_information(primary)

    # ── Days / hours on Zillow ────────────────────────────────────────────────
    days, hours, updated = extract_days_on_zillow(primary)
    result.days_on_zillow = days
    result.hours_on_zillow = hours
    result.listing_updated = updated

    return result
