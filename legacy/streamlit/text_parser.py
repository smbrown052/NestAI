import re
import pandas as pd


def clean_money(value):
    if not isinstance(value, str):
        return None
    match = re.search(r"\$?([\d,]+)", value)
    return int(match.group(1).replace(",", "")) if match else None


def parse_number(value):
    if not isinstance(value, str):
        return None
    match = re.search(r"(\d+)", value.replace(",", ""))
    return int(match.group(1)) if match else None


def parse_floor_from_unit(unit):
    if not isinstance(unit, str):
        return None

    unit = unit.strip().upper()

    if unit.startswith("PH"):
        return 99

    digits = re.sub(r"\D", "", unit)

    if len(digits) >= 4:
        return int(digits[:2])

    if len(digits) == 3:
        return int(digits[0])

    return None

def parse_has_den(floorplan_name, nearby_text=""):
    combined = f"{floorplan_name or ''} {nearby_text or ''}".lower()

    if "den" in combined:
        return True

    if isinstance(floorplan_name, str):
        name = floorplan_name.upper()
        if "D" in name and re.search(r"[A-Z]*D", name):
            return True

    return False

def extract_amenities_from_text(text):
    """
    Extract amenities from full apartment listing text.
    Searches Apartment Features, Community Amenities, and FAQ sections.
    """
    amenities = {
        "has_laundry": False,
        "has_gym": False,
        "has_fitness": False,
        "has_pool": False,
        "has_parking": False,
        "has_balcony": False,
        "has_patio": False,
        "has_security": False,
        "has_concierge": False,
    }
    
    text_lower = text.lower()
    
    # Look for laundry mentions
    if "washer" in text_lower and "dryer" in text_lower:
        amenities["has_laundry"] = True
    elif "in-unit laundry" in text_lower or "in unit laundry" in text_lower:
        amenities["has_laundry"] = True
    elif re.search(r"washer\s*[/&]\s*dryer", text_lower):
        amenities["has_laundry"] = True
    
    # Look for gym/fitness
    if "gym" in text_lower or "fitness" in text_lower or "fitness center" in text_lower:
        if "gym" in text_lower:
            amenities["has_gym"] = True
        if "fitness" in text_lower:
            amenities["has_fitness"] = True
    
    # Look for pool
    if "pool" in text_lower or "swimming pool" in text_lower:
        amenities["has_pool"] = True
    
    # Look for parking
    if "parking" in text_lower or "garage" in text_lower or "covered parking" in text_lower:
        amenities["has_parking"] = True
    
    # Look for balcony/patio
    if "balcony" in text_lower or "patio" in text_lower or "deck" in text_lower:
        if "balcony" in text_lower:
            amenities["has_balcony"] = True
        if "patio" in text_lower or "patios" in text_lower:
            amenities["has_patio"] = True
    
    # Look for security/concierge
    if "24" in text_lower and "hour" in text_lower and "security" in text_lower:
        amenities["has_security"] = True
    elif "security" in text_lower:
        amenities["has_security"] = True
    
    if "concierge" in text_lower:
        amenities["has_concierge"] = True
    
    return amenities


def parse_nearby_places(lines):
    nearby = []
    current_type = None
    prev_place_candidate = ""

    noise_terms = [
        "Washington Metropolitan Area Transit Authority Metrorail Silver Line Orange Line Blue Line",
        "Washington Metropolitan Area Transit Authority Metrorail Silver Line Orange Line",
        "Washington Metropolitan Area Transit Authority Metrorail",
        "Silver Line Orange Line Blue Line",
        "Silver Line Orange Line",
        "Blue Line",
    ]

    for line in lines:
        clean = line.strip()
        lower = clean.lower()

        # Start sections using "in", not exact match
        if "education" == lower or lower.startswith("education"):
            current_type = "School"
            prev_place_candidate = ""
            continue

        if "transit / subway" in lower:
            current_type = "Metro"
            prev_place_candidate = ""
            continue

        if lower.startswith("hospitals"):
            current_type = "Hospital"
            prev_place_candidate = ""
            continue

        # End sections
        if (
            lower.startswith("commuter rail")
            or lower.startswith("airports")
            or lower.startswith("getting around")
            or lower.startswith("shopping centers")
            or lower.startswith("parks and recreation")
            or lower.startswith("military bases")
            or lower.startswith("reviews")
        ):
            current_type = None
            prev_place_candidate = ""
            continue

        if current_type is None:
            continue

        if "walk:" in lower or "drive:" in lower:
            mode = "walk" if "walk:" in lower else "drive"

            minute_match = re.search(r"(\d+)\s*min", lower)
            # Use word boundary to avoid matching "min" in place of "mi"
            mile_match = re.search(r"([\d.]+)\s*mi\b", lower)

            minutes = int(minute_match.group(1)) if minute_match else None
            miles = float(mile_match.group(1)) if mile_match else None

            place_name = re.split(r"Walk:|Drive:", clean, flags=re.IGNORECASE)[0].strip()

            # When name and distance are on separate lines, the distance line
            # has an empty left-hand side — fall back to the previous content line.
            if not place_name and prev_place_candidate:
                place_name = prev_place_candidate

            for noise in noise_terms:
                place_name = place_name.replace(noise, "").strip()

            # Final fallback: never emit a blank place_name
            if not place_name:
                place_name = f"Nearby {current_type}"

            nearby.append({
                "place_type": current_type,
                "place_name": place_name,
                "minutes": minutes,
                "miles": miles,
                "travel_mode": mode,
            })
            prev_place_candidate = ""
        else:
            # Remember this line as a potential place name for the next distance line
            prev_place_candidate = clean

    return nearby


def summarize_building_nearby(nearby_places):
    summary = {
    "nearest_metro": None,
    "metro_min": None,
    "metro_travel_mode": None,

    "nearest_school": None,
    "school_min": None,
    "school_travel_mode": None,

    "nearest_hospital": None,
    "hospital_min": None,
    "hospital_travel_mode": None,
    }

    metros = [
        p for p in nearby_places
        if p["place_type"] == "Metro"
        and p["travel_mode"] == "walk"
        and p["minutes"] is not None
    ]

    schools = [
        p for p in nearby_places
        if p["place_type"] == "School"
        and p["travel_mode"] == "walk"
        and p["minutes"] is not None
    ]

    hospitals = [
        p for p in nearby_places
        if p["place_type"] == "Hospital"
        and p["minutes"] is not None
    ]

    if metros:
        nearest = min(metros, key=lambda x: x["minutes"])
        summary["nearest_metro"] = nearest["place_name"]
        summary["metro_min"] = nearest["minutes"]
        summary["metro_travel_mode"] = nearest["travel_mode"]

    if schools:
        nearest = min(schools, key=lambda x: x["minutes"])
        summary["nearest_school"] = nearest["place_name"]
        summary["school_min"] = nearest["minutes"]
        summary["school_travel_mode"] = nearest["travel_mode"]

    if hospitals:
        nearest = min(hospitals, key=lambda x: x["minutes"])
        summary["nearest_hospital"] = nearest["place_name"]
        summary["hospital_min"] = nearest["minutes"]
        summary["hospital_travel_mode"] = nearest["travel_mode"]

    return summary


def parse_walk_score(lines):
    """Parse the numeric walkability score from the 'Getting Around' section."""
    for i, line in enumerate(lines):
        if line.strip().lower() == "walkability":
            for j in range(i + 1, min(i + 4, len(lines))):
                stripped = lines[j].strip()
                if re.match(r"^\d{1,3}$", stripped):
                    score = int(stripped)
                    if 0 <= score <= 100:
                        return score
    return None


def parse_renter_rating(lines):
    """Parse the numeric renter rating (e.g. 2.5 out of 5) from listing text."""
    for i, line in enumerate(lines):
        if "renter rating" in line.strip().lower() and i > 0:
            try:
                rating = float(lines[i - 1].strip())
                if 0.0 <= rating <= 5.0:
                    return rating
            except ValueError:
                pass
    return None


def parse_apartment_text(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    property_title = ""
    address = ""

    for idx, line in enumerate(lines):
        if re.search(r"\b[A-Z]{2}\s+\d{5}\b", line):
            address = line
            if idx > 0:
                property_title = lines[idx - 1]
            break

    if not property_title:
        property_title = lines[0] if lines else ""

    if not address:
        address = lines[1] if len(lines) > 1 else ""

    # Extract amenities from full text
    building_amenities = extract_amenities_from_text(text)

    # Nearby uses the FULL page
    nearby_places = parse_nearby_places(lines)
    building_nearby = summarize_building_nearby(nearby_places)

    # Building-level scores shared by all units
    walk_score = parse_walk_score(lines)
    renter_rating = parse_renter_rating(lines)
    safety_score = round(renter_rating / 5.0 * 100) if renter_rating is not None else None

    # Units use ONLY the pricing section
    pricing_start = None

    for idx, line in enumerate(lines):
        if "Pricing & Floor Plans" in line:
            pricing_start = idx
            break

    if pricing_start is None:
        return {
            "property_title": property_title,
            "address": address,
            "nearby_places": nearby_places,
            "building_nearby": building_nearby,
            "building_amenities": building_amenities,
            "units": [],
            "unit_count": 0,
        }

    pricing_end = len(lines)
    stop_markers = [
        "Fees and Policies",
        "* Price shown",
        "Matterport 3D Tours",
        "About ",
        "About",
        "Contact",
        "Community Amenities",
        "Apartment Features",
        "Location",
    ]

    for idx in range(pricing_start + 1, len(lines)):
        if any(marker in lines[idx] for marker in stop_markers):
            pricing_end = idx
            break

    pricing_lines = lines[pricing_start:pricing_end]

    units = []

    current_floorplan = None
    current_beds = None
    current_baths = None
    current_floorplan_sqft = None

    i = 0

    while i < len(pricing_lines):
        line = pricing_lines[i]

        # Floorplan block version A:
        # A1U
        # $2,740 – $3,130
        # 1 Bed
        # 1 Bath
        # 502 Sq Ft
        if (
            i + 4 < len(pricing_lines)
            and "$" in pricing_lines[i + 1]
            and "Bed" in pricing_lines[i + 2]
            and "Bath" in pricing_lines[i + 3]
            and "Sq Ft" in pricing_lines[i + 4]
        ):
            current_floorplan = line
            current_beds = pricing_lines[i + 2]
            current_baths = pricing_lines[i + 3]
            current_floorplan_sqft = pricing_lines[i + 4].replace(" Sq Ft", "")

        # Floorplan block version B:
        # CD1
        # $2,889
        # Plus Fees
        # 1 Bed
        # 1 Bath
        # 831 Sq Ft
        elif (
            i + 5 < len(pricing_lines)
            and "$" in pricing_lines[i + 1]
            and (
                "Total Monthly Price" in pricing_lines[i + 2]
                or "Plus Fees" in pricing_lines[i + 2]
                or "Monthly Rent" in pricing_lines[i + 2]
            )
            and "Bed" in pricing_lines[i + 3]
            and "Bath" in pricing_lines[i + 4]
            and "Sq Ft" in pricing_lines[i + 5]
        ):
            current_floorplan = line
            current_beds = pricing_lines[i + 3]
            current_baths = pricing_lines[i + 4]
            current_floorplan_sqft = pricing_lines[i + 5].replace(" Sq Ft", "")

        # Unit block
        if line.lower() == "unit":
            if i + 6 < len(pricing_lines):
                unit_number = pricing_lines[i + 1]
                maybe_price_label = pricing_lines[i + 2].lower()
                price = pricing_lines[i + 3]
                maybe_sqft_label = pricing_lines[i + 4].lower()
                sqft = pricing_lines[i + 5]
                availability_raw = pricing_lines[i + 6]

                is_real_unit = (
                    maybe_price_label == "price"
                    and "square feet" in maybe_sqft_label
                    and "$" in price
                    and re.search(r"\d", sqft)
                    and (
                        "availibility" in availability_raw.lower()
                        or "availability" in availability_raw.lower()
                    )
                )

                if is_real_unit:
                    availability = (
                        availability_raw
                        .replace("availibility", "")
                        .replace("availability", "")
                        .strip()
                    )

                    unit = {
                        "property": property_title,
                        "address": address,
                        "floorplan": current_floorplan,
                        "unit": unit_number,
                        "floor": parse_floor_from_unit(unit_number),
                        "price": price,
                        "price_num": clean_money(price),
                        "beds": current_beds,
                        "beds_num": parse_number(current_beds),
                        "baths": current_baths,
                        "baths_num": parse_number(current_baths),
                        "sqft": sqft,
                        "sqft_num": parse_number(sqft),
                        "floorplan_sqft_range": current_floorplan_sqft,
                        "has_den": parse_has_den(current_floorplan, current_floorplan_sqft),
                        "availability": availability,
                        "walk_score": walk_score,
                        "safety_score": safety_score,
                    }

                    # Add building amenities to each unit
                    unit.update(building_amenities)
                    unit.update(building_nearby)
                    units.append(unit)

                    i += 7
                    continue

        i += 1

    return {
        "property_title": property_title,
        "address": address,
        "nearby_places": nearby_places,
        "building_nearby": building_nearby,
        "building_amenities": building_amenities,
        "units": units,
        "unit_count": len(units),
    }


def filter_units_by_request(df, request):
    if df.empty:
        return df

    filtered = df.copy()
    req = request.lower()

    if "den" in req:
        filtered = filtered[
            filtered["has_den"] == True
        ]
    if "studio" in req:
        filtered = filtered[filtered["beds_num"].fillna(0) == 0]

    if "one bed" in req or "1 bed" in req or "1 bedroom" in req:
        filtered = filtered[filtered["beds_num"] == 1]

    if "two bed" in req or "2 bed" in req or "2 bedroom" in req:
        filtered = filtered[filtered["beds_num"] == 2]

    if "three bed" in req or "3 bed" in req or "3 bedroom" in req:
        filtered = filtered[filtered["beds_num"] == 3]

    if "one bath" in req or "1 bath" in req or "1 bathroom" in req:
        filtered = filtered[filtered["baths_num"] == 1]

    if "two bath" in req or "2 bath" in req or "2 bathroom" in req:
        filtered = filtered[filtered["baths_num"] == 2]

    if "not on the first floor" in req or "not first floor" in req:
        filtered = filtered[(filtered["floor"].isna()) | (filtered["floor"] != 1)]

    metro_match = re.search(r"within\s+(\d+)\s*min.*metro", req)
    if metro_match and "metro_min" in filtered.columns:
        max_minutes = int(metro_match.group(1))
        filtered = filtered[
            filtered["metro_min"].notna()
            & (filtered["metro_min"] <= max_minutes)
        ]

    if "available now" in req or "now" in req:
        filtered = filtered[filtered["availability"].str.lower() == "now"]

    if "cheapest" in req or "lowest price" in req:
        filtered = filtered.sort_values("price_num", ascending=True)

    if "largest" in req or "most sqft" in req:
        filtered = filtered.sort_values("sqft_num", ascending=False)

    if "laundry" in req or "washer" in req or "dryer" in req:
        filtered = filtered[filtered["has_laundry"] == True]

    if "gym" in req or "fitness" in req:
        filtered = filtered[(filtered["has_gym"] == True) | (filtered["has_fitness"] == True)]

    if "pool" in req:
        filtered = filtered[filtered["has_pool"] == True]

    if "parking" in req:
        filtered = filtered[filtered["has_parking"] == True]

    # Search user-supplied notes for any keywords not already matched above
    if "user_notes" in filtered.columns:
        notes_col = filtered["user_notes"].fillna("").str.lower()
        # Build combined text: nearest_metro + user_notes
        metro_col = (
            filtered["nearest_metro"].fillna("").str.lower()
            if "nearest_metro" in filtered.columns
            else pd.Series("", index=filtered.index)
        )
        combined_text = metro_col + " " + notes_col

        # Strip common stop words and structured filter keywords, then match the
        # remaining phrase as a substring in combined_text.  This lets users type
        # e.g. "green line" and match only units whose notes contain that phrase.
        _stop_words = {
            "show", "me", "apartments", "units", "with", "near", "a", "an", "the",
            "that", "have", "has", "in", "to", "for", "and", "or", "not", "is",
            "are", "find", "filter", "looking", "want", "i", "only",
            "den", "studio", "bed", "bedroom", "beds", "bath", "bathroom", "baths",
            "floor", "metro", "available", "now", "cheapest", "lowest", "largest",
            "sqft", "laundry", "washer", "dryer", "gym", "fitness", "pool", "parking",
            "under", "over", "above", "below", "price", "rent", "one", "two", "three",
            "1", "2", "3", "first", "within", "min", "minutes", "least", "at",
        }
        remaining_words = [w for w in req.split() if w not in _stop_words]
        search_phrase = " ".join(remaining_words).strip()

        if search_phrase:
            notes_mask = combined_text.str.contains(re.escape(search_phrase), na=False)
            if notes_mask.any():
                filtered = filtered[notes_mask]

    return filtered

