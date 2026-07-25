"""
parser/home_listing.py
House listing parser for Zillow-format rental pages.

Handles two layouts that appear when copying a Zillow page:
  1. Single-listing detail section (title, price, beds/baths/sqft, scores).
  2. Search-results section (compact "N bd N ba SQFTsqftTYPE" lines with address).

Returns a dict whose structure mirrors that of parse_apartment_text so the
Houses tab can display results without special-casing.
"""

from __future__ import annotations

import re


# ── Helpers ───────────────────────────────────────────────────────────────────

_ADDRESS_RE = re.compile(r"\b[A-Z]{2}\s+\d{5}\b")
_PRICE_LINE_RE = re.compile(r"^\$[\d,]+/mo", re.IGNORECASE)

# Compact search-result line: "1 bd1 ba805 sqftTownhouse for rent"
_COMPACT_RE = re.compile(
    r"^(\d+(?:\.\d+)?)\s*bds?\s*(\d+(?:\.\d+)?)\s*ba\s*([\d,]+)\s*sqft\s*(.+?)$",
    re.IGNORECASE,
)


def _clean_money(value: str) -> int | None:
    """Return the integer dollar amount from a string like '$2,245'."""
    if not isinstance(value, str):
        return None
    m = re.search(r"\$?([\d,]+)", value)
    return int(m.group(1).replace(",", "")) if m else None


def _parse_number(value: str) -> int | None:
    if not isinstance(value, str):
        return None
    m = re.search(r"(\d[\d,]*)", value)
    return int(m.group(1).replace(",", "")) if m else None


def _extract_score(lines: list[str], start: int) -> int | None:
    """Return the first 0-100 integer found within three lines after *start*."""
    for j in range(start + 1, min(start + 4, len(lines))):
        m = re.match(r"^(\d{1,3})$", lines[j].strip())
        if m:
            score = int(m.group(1))
            if 0 <= score <= 100:
                return score
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def parse_house_listing(raw_text: str) -> dict:
    """
    Parse one pasted Zillow house/townhouse listing page and return:

    {
        property_title: str | None,
        address: str | None,
        building_nearby: dict,     # always {} — Zillow doesn't expose metro data
        nearby_places: list,       # always [] for now
        building_amenities: dict,  # always {} for now
        units: list[dict],         # one entry per parsed listing
        unit_count: int,
        walk_score: int | None,
        transit_score: int | None,
        bike_score: int | None,
    }
    """
    if not raw_text or not raw_text.strip():
        return {
            "property_title": None,
            "address": None,
            "building_nearby": {},
            "nearby_places": [],
            "building_amenities": {},
            "units": [],
            "unit_count": 0,
            "walk_score": None,
            "transit_score": None,
            "bike_score": None,
        }

    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]

    # ── 1. Parse the primary detail listing (top of the Zillow page) ─────────

    primary_price_str: str | None = None
    primary_address: str | None = None
    primary_beds: int | None = None
    primary_baths: float | None = None
    primary_sqft: int | None = None
    primary_type: str | None = None
    primary_availability: str | None = None
    walk_score: int | None = None
    transit_score: int | None = None
    bike_score: int | None = None

    # Only scan the first 120 lines for the detail section so we don't
    # accidentally pick up prices from the search-results section below.
    detail_lines = lines[:120]

    for i, line in enumerate(detail_lines):
        # Price: "$2,245/mo" or "$2,245/mo Total monthly price"
        if primary_price_str is None:
            m = re.match(r"^(\$[\d,]+)/mo", line, re.IGNORECASE)
            if m:
                primary_price_str = m.group(1)
                continue

        # Address: first line matching "CITY, ST XXXXX" pattern
        if primary_address is None and _ADDRESS_RE.search(line):
            primary_address = line
            continue

        # Beds — "beds" line → previous line is the count
        if line.lower() == "beds" and i > 0:
            try:
                primary_beds = int(detail_lines[i - 1])
            except (ValueError, IndexError):
                pass

        # Baths — "baths" line → previous line is the count
        if line.lower() == "baths" and i > 0:
            try:
                primary_baths = float(detail_lines[i - 1])
            except (ValueError, IndexError):
                pass

        # Sqft — "sqft" line → previous line is the number
        if line.lower() == "sqft" and i > 0 and primary_sqft is None:
            primary_sqft = _parse_number(detail_lines[i - 1])

        # Property type
        if primary_type is None:
            for kw in ("House", "Townhouse", "Condo", "Single family", "Duplex", "Mobile"):
                if line.lower().startswith(kw.lower()):
                    primary_type = re.sub(
                        r"\s+for\s+rent\s*$", "", line, flags=re.IGNORECASE
                    ).strip()
                    break

        # Availability
        if primary_availability is None:
            m = re.match(r"^Available\s+(.+)", line, re.IGNORECASE)
            if m:
                primary_availability = m.group(1).strip()

    # Walk / Transit / Bike scores — scan full text
    for i, line in enumerate(lines):
        if walk_score is None and "Walk Score" in line:
            walk_score = _extract_score(lines, i)
        if transit_score is None and "Transit Score" in line:
            transit_score = _extract_score(lines, i)
        if bike_score is None and "Bike Score" in line:
            bike_score = _extract_score(lines, i)

    # ── 2. Build the primary unit record ──────────────────────────────────────

    units: list[dict] = []

    if primary_address and primary_price_str:
        title = primary_address.split(",")[0].strip()
        units.append({
            "property": title,
            "address": primary_address,
            "price": primary_price_str,
            "price_num": _clean_money(primary_price_str),
            "beds": f"{primary_beds} bed" if primary_beds is not None else None,
            "beds_num": primary_beds,
            "baths": f"{primary_baths} bath" if primary_baths is not None else None,
            "baths_num": primary_baths,
            "sqft": str(primary_sqft) if primary_sqft is not None else None,
            "sqft_num": primary_sqft,
            "type": primary_type,
            "availability": primary_availability,
            "walk_score": walk_score,
            "transit_score": transit_score,
            "bike_score": bike_score,
        })

    # ── 3. Parse search-results section (compact format) ──────────────────────

    seen_addresses: set[str] = {u["address"] for u in units}

    for i, line in enumerate(lines):
        m = _COMPACT_RE.match(line)
        if not m:
            continue

        beds = float(m.group(1))
        baths = float(m.group(2))
        sqft = _parse_number(m.group(3))
        ptype = re.sub(r"\s*for\s+rent\s*$", "", m.group(4), flags=re.IGNORECASE).strip()

        # Price — search backward up to 5 lines for "$X,XXX/mo"
        price_str: str | None = None
        price_num: int | None = None
        for j in range(i - 1, max(i - 6, -1), -1):
            pm = re.match(r"^(\$[\d,]+)/mo", lines[j], re.IGNORECASE)
            if pm:
                price_str = pm.group(1)
                price_num = _clean_money(price_str)
                break

        # Address — search forward up to 4 lines
        addr: str | None = None
        for j in range(i + 1, min(i + 5, len(lines))):
            if _ADDRESS_RE.search(lines[j]):
                addr = lines[j]
                break

        if not addr or not price_str:
            continue

        # If this compact entry matches an existing unit (e.g. the primary listing
        # which was created from the detail section but may have missing fields),
        # back-fill any missing beds/baths/sqft instead of adding a duplicate.
        existing = next((u for u in units if u.get("address") == addr), None)
        if existing:
            if existing["beds_num"] is None:
                existing["beds_num"] = int(beds)
                existing["beds"] = f"{int(beds)} bed"
            if existing["baths_num"] is None:
                existing["baths_num"] = baths
                existing["baths"] = f"{baths} bath"
            if existing["sqft_num"] is None and sqft is not None:
                existing["sqft_num"] = sqft
                existing["sqft"] = str(sqft)
            if existing["type"] is None:
                existing["type"] = ptype
            continue

        seen_addresses.add(addr)
        title = addr.split(",")[0].strip()
        units.append({
            "property": title,
            "address": addr,
            "price": price_str,
            "price_num": price_num,
            "beds": f"{int(beds)} bed",
            "beds_num": int(beds),
            "baths": f"{baths} bath",
            "baths_num": baths,
            "sqft": str(sqft) if sqft is not None else None,
            "sqft_num": sqft,
            "type": ptype,
            "availability": None,
            "walk_score": None,
            "transit_score": None,
            "bike_score": None,
        })

    # ── 4. Derive property_title from primary address ─────────────────────────

    property_title: str | None = None
    if primary_address:
        property_title = primary_address.split(",")[0].strip()
    elif units:
        property_title = units[0].get("property")
    elif lines:
        property_title = lines[0]

    return {
        "property_title": property_title,
        "address": primary_address or "",
        "building_nearby": {},
        "nearby_places": [],
        "building_amenities": {},
        "units": units,
        "unit_count": len(units),
        "walk_score": walk_score,
        "transit_score": transit_score,
        "bike_score": bike_score,
    }
