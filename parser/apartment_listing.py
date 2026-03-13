import re


def extract_field(pattern, text, flags=0):
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None


def normalize_text(text):
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)

    text = re.sub(r"(?i)\bUnit(?=[A-Za-z]?\d{2,4}[A-Za-z]?)", "Unit ", text)
    text = re.sub(r"(?i)\bprice(?=\$)", "price ", text)
    text = re.sub(r"(?i)\bsquare feet(?=\d)", "square feet ", text)
    text = re.sub(
        r"(?i)\bavail(?:ability|ibility)(?=Now|Immediately|[A-Z][a-z]{2,8}\s+\d{1,2})",
        "availability ",
        text,
    )

    text = re.sub(r"\n+", "\n", text)
    text = re.sub(r" +", " ", text)
    return text.strip()


def extract_available_units_section(lines):
    start_idx = 0
    for i, line in enumerate(lines):
        if re.search(r"\bpricing\s*&\s*floor\s*plans\b", line, re.IGNORECASE):
            start_idx = i
            break
    return lines[start_idx:]


def clean_list(items):
    seen = set()
    cleaned = []

    for item in items or []:
        if not item:
            continue
        value = re.sub(r"\s+", " ", str(item)).strip(" ,;:-")
        if not value:
            continue

        key = value.lower()
        if key not in seen:
            seen.add(key)
            cleaned.append(value)

    return cleaned


def split_feature_items(raw_text):
    if not raw_text:
        return []

    text = str(raw_text)

    text = text.replace("•", "\n")
    text = text.replace("|", "\n")
    text = text.replace("·", "\n")
    text = text.replace(";", "\n")

    parts = []
    for chunk in text.split("\n"):
        chunk = chunk.strip()
        if not chunk:
            continue

        subparts = [p.strip() for p in re.split(r",(?=\s*[A-Za-z])", chunk) if p.strip()]
        parts.extend(subparts)

    return clean_list(parts)


def extract_section_items(text, section_names, stop_names=None):
    if stop_names is None:
        stop_names = []

    all_stops = section_names + stop_names + [
        "available units",
        "floor plan",
        "pricing",
        "price range",
        "unit details",
        "pet policy",
        "schools",
        "neighborhood",
        "lease terms",
        "application fee",
    ]

    section_pattern = r"(?im)^\s*(?:%s)\s*$" % "|".join(re.escape(name) for name in section_names)
    stop_pattern = r"(?im)^\s*(?:%s)\s*$" % "|".join(re.escape(name) for name in all_stops)

    matches = list(re.finditer(section_pattern, text))
    if not matches:
        return []

    items = []

    for match in matches:
        start = match.end()
        following_text = text[start:]

        stop_match = re.search(stop_pattern, following_text)
        block = following_text[:stop_match.start()] if stop_match else following_text

        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue

        block_text = "\n".join(lines)
        items.extend(split_feature_items(block_text))

    return clean_list(items)


def infer_amenities(text):
    keywords = [
        "Pool",
        "Fitness Center",
        "Gym",
        "Clubhouse",
        "Business Center",
        "Coworking",
        "Concierge",
        "Package Service",
        "Package Locker",
        "Elevator",
        "Garage",
        "Covered Parking",
        "Parking",
        "EV Charging",
        "Roof Deck",
        "Rooftop",
        "Sundeck",
        "Courtyard",
        "Grill",
        "Picnic Area",
        "Pet Spa",
        "Dog Park",
        "Bike Storage",
        "Bike Room",
        "Storage",
        "Laundry Facilities",
        "On-Site Maintenance",
        "On-Site Management",
        "Doorman",
        "Media Room",
        "Resident Lounge",
        "Conference Room",
        "Playground",
        "Tennis Court",
        "Basketball Court",
        "Spa",
        "Sauna",
        "Hot Tub",
    ]

    found = []
    for keyword in keywords:
        if re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE):
            found.append(keyword)

    return clean_list(found)


def infer_apartment_features(text):
    keywords = [
        "Washer/Dryer",
        "In Unit Washer & Dryer",
        "Dishwasher",
        "Air Conditioning",
        "Balcony",
        "Patio",
        "Hardwood Floors",
        "Walk-In Closets",
        "Stainless Steel Appliances",
        "Microwave",
        "Refrigerator",
        "Ceiling Fan",
        "Fireplace",
        "Double Vanity",
        "High Ceilings",
        "Island Kitchen",
        "Granite Countertops",
        "Quartz Countertops",
        "Loft Layout",
        "Den",
        "Wheelchair Accessible",
        "Cable Ready",
        "Smoke Free",
    ]

    found = []
    for keyword in keywords:
        if re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE):
            found.append(keyword)

    return clean_list(found)


def extract_amenities(text):
    items = extract_section_items(
        text,
        section_names=[
            "Amenities",
            "Community Amenities",
            "Property Amenities",
            "Building Amenities",
        ],
        stop_names=[
            "Apartment Features",
            "Unit Features",
            "Interior Features",
            "Walkability",
            "Neighborhood",
        ],
    )

    if not items:
        items = infer_amenities(text)

    return clean_list(items)


def extract_apartment_features(text):
    items = extract_section_items(
        text,
        section_names=[
            "Apartment Features",
            "Unit Features",
            "Interior Features",
            "Home Features",
            "Apartment Amenities",
        ],
        stop_names=[
            "Amenities",
            "Community Amenities",
            "Walkability",
            "Neighborhood",
        ],
    )

    if not items:
        items = infer_apartment_features(text)

    return clean_list(items)


def extract_walkability(text):
    walk_score = extract_field(r"\bWalk Score\b[:\s-]*(\d{1,3})", text, re.IGNORECASE)
    transit_score = extract_field(r"\bTransit Score\b[:\s-]*(\d{1,3})", text, re.IGNORECASE)
    bike_score = extract_field(r"\bBike Score\b[:\s-]*(\d{1,3})", text, re.IGNORECASE)

    walk_label = extract_field(
        r"\bWalk Score\b[:\s-]*\d{1,3}\s*[\-\u2013\u2014]?\s*([A-Za-z][A-Za-z ]+)",
        text,
        re.IGNORECASE,
    )
    transit_label = extract_field(
        r"\bTransit Score\b[:\s-]*\d{1,3}\s*[\-\u2013\u2014]?\s*([A-Za-z][A-Za-z ]+)",
        text,
        re.IGNORECASE,
    )
    bike_label = extract_field(
        r"\bBike Score\b[:\s-]*\d{1,3}\s*[\-\u2013\u2014]?\s*([A-Za-z][A-Za-z ]+)",
        text,
        re.IGNORECASE,
    )

    return {
        "walk_score": int(walk_score) if walk_score else None,
        "transit_score": int(transit_score) if transit_score else None,
        "bike_score": int(bike_score) if bike_score else None,
        "walk_label": walk_label,
        "transit_label": transit_label,
        "bike_label": bike_label,
    }

def parse_unit_records(unit_text):
    """
    Parse repeated unit blocks like:

    Unit
    1631
    price
    $2,656
    square feet
    724
    availibilityNow

    or similar formatting variations.
    """
    pattern = re.compile(
        r"Unit\s*(?P<unit>[A-Za-z]?\d{3,4}[A-Za-z]?)\s*"
        r"(?:.*?\bprice\b\s*(?P<price>\$[\d,]+(?:\.\d{2})?))\s*"
        r"(?:.*?\bsquare feet\b\s*(?P<sqft>[\d,]{3,5}))\s*"
        r"(?:.*?\bavail(?:ability|ibility)\b\s*(?P<availability>Now|Immediately|[A-Z][a-z]{2,8}\s+\d{1,2}))",
        re.IGNORECASE | re.DOTALL,
    )

    matches = []
    seen = set()

    for match in pattern.finditer(unit_text):
        unit_label = match.group("unit")
        unit_price = match.group("price")
        unit_sqft = match.group("sqft")
        available_date = match.group("availability")

        key = (unit_label, unit_price, unit_sqft, available_date)
        if key in seen:
            continue
        seen.add(key)

        row_text = (
            f"Unit {unit_label} | "
            f"price {unit_price} | "
            f"square feet {unit_sqft} | "
            f"availability {available_date}"
        )

        matches.append(
            {
                "unit_label": unit_label,
                "unit_price": unit_price,
                "unit_sqft": unit_sqft,
                "available_date": available_date,
                "row_text": row_text,
            }
        )

    return matches
print("UNIT TEXT START")
print(unit_text[:3000])
print("UNIT TEXT END")
def parse_apartment_listing(raw_text: str) -> dict:
    """
    Parse one pasted apartment listing text block and return:
    - property-level fields
    - amenities
    - apartment features
    - walkability
    - a list of unit records
    """
    if not raw_text or not raw_text.strip():
        return {
            "property_title": None,
            "floorplan_name": None,
            "beds": None,
            "baths": None,
            "floorplan_price_range": None,
            "floorplan_sqft_range": None,
            "floorplan_has_den": False,
            "amenities": [],
            "apartment_features": [],
            "walkability": {
                "walk_score": None,
                "transit_score": None,
                "bike_score": None,
                "walk_label": None,
                "transit_label": None,
                "bike_label": None,
            },
            "units": [],
        }

    text = normalize_text(raw_text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    property_title = lines[0] if lines else None

    floorplan_name = extract_field(r"([0-9xX]+\s+[A-Za-z][A-Za-z0-9\s-]*)", text)
    floorplan_price_range = extract_field(r"(\$[\d,]+\s*-\s*\$[\d,]+)", text)
    beds = extract_field(r"(\d+(?:\.\d+)?)\s*Bed", text, re.IGNORECASE)
    baths = extract_field(r"(\d+(?:\.\d+)?)\s*Bath", text, re.IGNORECASE)
    floorplan_sqft_range = extract_field(
        r"([\d,]+\s*-\s*[\d,]+\s*Sq\s*Ft)", text, re.IGNORECASE
    )
    floorplan_has_den = bool(re.search(r"\bDen\b", text, re.IGNORECASE))

    amenities = extract_amenities(text)
    apartment_features = extract_apartment_features(text)
    walkability = extract_walkability(text)

    unit_lines = extract_available_units_section(lines)
    unit_lines = [
    line
    for line in unit_lines
    if line.lower()
    not in {"unit", "base price", "sq ft", "availability", "unit details"}
]

    unit_text = "\n".join(unit_lines)
    unit_records = parse_unit_records(unit_text)

    return {
        "property_title": property_title,
        "floorplan_name": floorplan_name,
        "beds": beds,
        "baths": baths,
        "floorplan_price_range": floorplan_price_range,
        "floorplan_sqft_range": floorplan_sqft_range,
        "floorplan_has_den": floorplan_has_den,
        "amenities": amenities,
        "apartment_features": apartment_features,
        "walkability": walkability,
        "units": unit_records,
    }
