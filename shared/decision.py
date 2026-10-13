"""Authoritative deterministic decisions; unknown facts are never invented."""

from __future__ import annotations

from typing import Any

from shared.constraints import Constraints, filter_rows, number, pet_policy

DEFAULT_PRIORITIES = {"price": 4.0, "space": 2.0, "commute": 1.0, "walkability": 1.0, "pets": 1.0}


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    aliases = {
        "price_num": ("monthly_rent", "rent_price", "unit_price"),
        "sqft_num": ("square_feet", "unit_sqft"),
        "beds_num": ("bedrooms",), "baths_num": ("bathrooms",),
        "property": ("display_name", "address"),
        "unit": ("unit_number",), "floor": ("floor_level",),
    }
    for name, alternatives in aliases.items():
        if result.get(name) is None:
            result[name] = next((row[k] for k in alternatives if row.get(k) is not None), None)
    for name in ("price_num", "sqft_num", "beds_num", "baths_num", "floor"):
        result[name] = number(result.get(name))
    result["unit"] = str(result["unit"]) if result.get("unit") is not None else ""
    result["property"] = str(result.get("property") or "Unknown property")
    result["pet_status"] = pet_policy(result.get("pets_policy"))
    known_fees = [number(result.get(f"extra_{k}")) for k in ("parking", "utilities", "pet_fee", "renters_insurance")]
    result["monthly_total"] = (
        result["price_num"] + sum(f or 0 for f in known_fees)
        if result["price_num"] is not None else None
    )
    result["fees_complete"] = all(f is not None for f in known_fees)
    return result


def comparison(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Deltas are B minus A: positive rent delta means A is cheaper."""
    a, b = normalize_row(a), normalize_row(b)
    deltas = {}
    for label, field in (("price", "price_num"), ("space", "sqft_num"), ("total_cost", "monthly_total")):
        x, y = number(a.get(field)), number(b.get(field))
        deltas[label] = None if x is None or y is None else y - x
    x, y = number(a.get("commute_minutes")), number(b.get("commute_minutes"))
    deltas["commute"] = None if x is None or y is None else y - x
    advantages, compromises, unknowns = [], [], []
    price, space, commute = deltas["price"], deltas["space"], deltas["commute"]
    if price is None:
        unknowns.append("Rent comparison unavailable")
    elif price > 0:
        advantages.append(f"${price:,.0f}/mo less expensive")
    elif price < 0:
        compromises.append(f"${-price:,.0f}/mo more expensive")
    if space is None:
        unknowns.append("Space comparison unavailable")
    elif space < 0:
        advantages.append(f"{-space:g} sq ft more space")
    elif space > 0:
        compromises.append(f"{space:g} sq ft less space")
    if commute is not None:
        if commute > 0:
            advantages.append(f"{commute:g} min shorter commute")
        elif commute < 0:
            compromises.append(f"{-commute:g} min longer commute")
    for key, label in (("has_laundry", "in-unit laundry"), ("has_pool", "pool"), ("has_parking", "parking"), ("has_fitness", "fitness center")):
        if a.get(key) is True and b.get(key) is False:
            advantages.append(f"Has {label}")
        elif a.get(key) is False and b.get(key) is True:
            compromises.append(f"No {label} (alternative has it)")
    return {
        "a": {"property": a["property"], "unit": a["unit"]},
        "b": {"property": b["property"], "unit": b["unit"]},
        "deltas": deltas, "advantages": advantages, "compromises": compromises,
        "unknowns": unknowns,
        "compromise_summary": "; ".join(compromises) or "No material compromise identified from known facts.",
    }


def rank_rows(rows: list[dict[str, Any]], priorities: dict[str, float] | None = None,
              constraints: Constraints | dict | None = None, profile: dict | None = None) -> list[dict[str, Any]]:
    weights = dict(DEFAULT_PRIORITIES if priorities is None else priorities)
    if set(weights) - set(DEFAULT_PRIORITIES):
        raise ValueError("Unsupported priority.")
    if not weights or any(isinstance(v, bool) or not isinstance(v, (int, float)) or number(v) is None or v < 0 for v in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError("Priorities must be finite nonnegative numbers with a positive total.")
    requirements = constraints if isinstance(constraints, Constraints) else Constraints.from_dict(constraints)
    options = filter_rows([normalize_row(r) for r in rows], requirements)
    profile = profile or {}
    prices = [r["price_num"] for r in options if r["price_num"] is not None and r["price_num"] > 0]
    areas = [r["sqft_num"] for r in options if r["sqft_num"] is not None and r["sqft_num"] > 0]

    def scale(value, population, inverse=False):
        if value is None or value <= 0 or not population:
            return None
        lower, upper = min(population), max(population)
        fraction = (value - lower) / (upper - lower) if upper != lower else 0.5
        return 100 * (1 - fraction if inverse else fraction)

    for row in options:
        components = {
            "price": scale(row["price_num"], prices, True),
            "space": scale(row["sqft_num"], areas),
            "commute": None,
            "walkability": number(row.get("official_walk_score")) if number(row.get("official_walk_score")) is not None else number(row.get("walk_score")),
            "pets": None,
        }
        commute = number(row.get("commute_minutes"))
        if commute is not None:
            components["commute"] = max(0.0, 100 - commute * 2)
        pet_preference = profile.get("pets", "No preference")
        if pet_preference in {"Yes", "No"} and row["pet_status"] != "unknown":
            components["pets"] = 100.0 if row["pet_status"] == pet_preference.lower() else 0.0
        budget = number(profile.get("max_budget"))
        if budget and row["price_num"] is not None and row["price_num"] > budget:
            components["price"] = max(0.0, (components["price"] or 0) - 50 * (row["price_num"] / budget - 1))
        total_weight = sum(weights.values())
        row["components"] = {
            key: {"value": components[key], "weight": weight,
                  "contribution": (50.0 if components[key] is None else components[key]) * weight / total_weight,
                  "known": components[key] is not None}
            for key, weight in weights.items()
        }
        row["score"] = round(sum(c["contribution"] for c in row["components"].values()), 4)
        row["confidence"] = round(sum(c["weight"] for c in row["components"].values() if c["known"]) / total_weight, 4)
        row["unmet_preferences"] = []
        if pet_preference in {"Yes", "No"}:
            if row["pet_status"] == "unknown":
                row["unmet_preferences"].append("Pet policy unknown")
            elif row["pet_status"] != pet_preference.lower():
                row["unmet_preferences"].append("Pet preference mismatch")
        peers = [r["price_num"] for r in options if r["beds_num"] == row["beds_num"] and r["price_num"] is not None]
        row["peer_group"] = f"Eligible saved options with {row['beds_num']:g} bedrooms" if row["beds_num"] is not None else "Bedroom count unknown"
        row["peer_count"] = len(peers) if row["beds_num"] is not None else 0
        row["peer_average"] = sum(peers) / len(peers) if len(peers) > 1 and row["beds_num"] is not None else None
    options.sort(key=lambda r: (-r["score"], str(r.get("property_id", r["property"])), r["unit"]))
    for index, row in enumerate(options):
        row["rank"] = index + 1
        row["comparison"] = comparison(row, options[index + 1]) if index + 1 < len(options) else None
    return options


def sensitivity(rows: list[dict], priorities: dict | None = None, constraints=None, profile=None) -> list[dict]:
    base = dict(DEFAULT_PRIORITIES if priorities is None else priorities)
    scenarios = []
    for key in base:
        changed = {**base, key: base[key] * 2 + 1}
        ranked = rank_rows(rows, changed, constraints, profile)
        scenarios.append({"priority": key, "priorities": changed,
                          "winner": {"property": ranked[0]["property"], "unit": ranked[0]["unit"], "score": ranked[0]["score"]} if ranked else None})
    return scenarios
