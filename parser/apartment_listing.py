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
        if re.search(r"available units", line, re.IGNORECASE):
            start_idx = i + 1
            break
    return lines[start_idx:]


def parse_unit_records(unit_text):
    pattern = re.compile(
        r"Unit\s*(?P<unit>[A-Za-z]?\d{2,4}[A-Za-z]?)"
        r".{0,60}?price\s*(?P<price>\$[\d,]+(?:\.\d{2})?)"
        r".{0,60}?square feet\s*(?P<sqft>\d{3,4})"
        r".{0,60}?availability\s*(?P<availability>Now|Immediately|[A-Z][a-z]{2,8}\s+\d{1,2})",
        re.IGNORECASE | re.DOTALL,
    )

    matches = []
    for match in pattern.finditer(unit_text):
        unit_label = match.group("unit")
        unit_price = match.group("price")
        unit_sqft = match.group("sqft")
        available_date = match.group("availability")

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


def parse_apartment_listing(raw_text: str) -> dict:
    """
    Parse one pasted apartment listing text block and return:
    - property-level fields
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
        "units": unit_records,
    }