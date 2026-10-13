"""Validated constraints shared by API ranking, reports and the legacy parser."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, fields
from typing import Any


class ConstraintError(ValueError):
    pass


@dataclass(frozen=True)
class Constraints:
    rent_lt: float | None = None
    rent_lte: float | None = None
    min_sqft: float | None = None
    min_beds: float | None = None
    min_baths: float | None = None
    exclude_floors: tuple[int, ...] = ()
    pet_friendly: bool = False
    max_transit_walk_minutes: float | None = None
    available_now: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "Constraints":
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ConstraintError("Constraints must be an object.")
        allowed = {f.name for f in fields(cls)}
        if set(value) - allowed:
            raise ConstraintError("Unsupported constraint fields.")
        cleaned = dict(value)
        for name in allowed - {"exclude_floors", "pet_friendly", "available_now"}:
            raw = cleaned.get(name)
            if raw is not None:
                if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw < 0:
                    raise ConstraintError(f"{name} must be a finite nonnegative number.")
        for name in ("pet_friendly", "available_now"):
            if name in cleaned and not isinstance(cleaned[name], bool):
                raise ConstraintError(f"{name} must be true or false.")
        excluded = cleaned.get("exclude_floors", ())
        if not isinstance(excluded, (list, tuple)) or any(
            isinstance(n, bool) or not isinstance(n, int) or n < 0 for n in excluded
        ):
            raise ConstraintError("Excluded floors must be nonnegative integers.")
        cleaned["exclude_floors"] = tuple(excluded)
        return cls(**cleaned)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> list[str]:
        labels = []
        for key, operator, unit in (
            ("rent_lt", "<", "/month"), ("rent_lte", "≤", "/month"),
            ("min_sqft", "≥", "sq ft"), ("min_beds", "≥", "bedrooms"),
            ("min_baths", "≥", "bathrooms"),
            ("max_transit_walk_minutes", "≤", "minutes walking to transit"),
        ):
            value = getattr(self, key)
            if value is not None:
                labels.append(f"{key.replace('_', ' ')} {operator} {value:g} {unit}")
        if self.exclude_floors:
            labels.append("Exclude floors: " + ", ".join(map(str, self.exclude_floors)))
        if self.pet_friendly:
            labels.append("Confirmed pet-friendly required")
        if self.available_now:
            labels.append("Confirmed available now required")
        return labels


def parse_constraints(request: str) -> Constraints:
    """Parse common requirements without a provider; reject unrecognized intent."""
    if not isinstance(request, str) or len(request) > 4000:
        raise ConstraintError("Enter a request of at most 4,000 characters.")
    text = request.lower().strip()
    if not text:
        return Constraints()
    remaining = text
    values: dict[str, Any] = {}

    def consume(pattern: str, callback) -> None:
        nonlocal remaining
        matches = list(re.finditer(pattern, remaining))
        for match in matches:
            callback(match)
        remaining = re.sub(pattern, " ", remaining)

    number = r"(\d[\d,]*(?:\.\d+)?)"

    def numeric(key, match):
        if key in values:
            raise ConstraintError("Specify one boundary for each requirement.")
        values[key] = float(match.group(1).replace(",", ""))

    # Monetary intent must be explicit; otherwise "under 10 min" is not rent.
    rent_prefix = r"(?:under|less than|below)\s*"
    rent_units = r"(?:\s*(?:dollars|per month|/month|a month|monthly|/mo))*"
    consume(rent_prefix + r"\$\s*" + number + rent_units,
            lambda m: numeric("rent_lt", m))
    consume(rent_prefix + number + r"\s*(?:dollars|per month|/month|a month|monthly|/mo)",
            lambda m: numeric("rent_lt", m))
    consume(r"(?:at most|up to|no more than|maximum rent(?: of)?)\s*\$\s*" + number + rent_units,
            lambda m: numeric("rent_lte", m))
    consume(r"(?:at most|up to|no more than|maximum rent(?: of)?)\s*" + number + r"\s*(?:dollars|per month|/month|a month|monthly|/mo)",
            lambda m: numeric("rent_lte", m))
    consume(r"(?:at least|minimum(?: of)?|min)?\s*" + number + r"\s*(?:square feet|sq\.?\s*ft|sqft)",
            lambda m: numeric("min_sqft", m))
    consume(r"(?:at least|minimum(?: of)?|min)?\s*" + number + r"\s*(?:bedrooms?|beds?|bd)\b",
            lambda m: numeric("min_beds", m))
    consume(r"(?:at least|minimum(?: of)?|min)?\s*" + number + r"\s*(?:bathrooms?|baths?|ba)\b",
            lambda m: numeric("min_baths", m))
    consume(r"\bstudio\b", lambda m: values.update(min_beds=0))
    consume(r"(?:not(?: on)?|exclude|excluding)\s*(?:the\s*)?(first|\d+(?:st|nd|rd|th)?)\s*floor",
            lambda m: values.update(exclude_floors=(*values.get("exclude_floors", ()),
                                                    1 if m.group(1) == "first" else int(re.sub(r"\D", "", m.group(1))))))
    consume(r"(?:within|at most|under)\s*" + number + r"\s*(?:min(?:utes?)?)\s*(?:walk(?:ing)?(?:\s*(?:of|to|from))?\s*)(?:subway|public transit|transit|metro)",
            lambda m: numeric("max_transit_walk_minutes", m))
    consume(r"(?:must (?:allow|accept) pets|pet[- ]friendly|pets (?:required|allowed)|allow pets)",
            lambda m: values.update(pet_friendly=True))
    consume(r"\b(?:available now|immediately available)\b", lambda m: values.update(available_now=True))
    remaining = re.sub(r"\b(?:only|show|me|units?|homes?|apartments?|listings?|with|and|that|are|have|has|must|be|please|per month|monthly rent|rent)\b", " ", remaining)
    remaining = re.sub(r"[\s,.;:]+", "", remaining)
    if remaining or not values:
        raise ConstraintError("Unsupported or ambiguous request. Use rent, square footage, bedrooms, bathrooms, floor exclusions, pet-friendly, or walking time to transit.")
    return Constraints.from_dict(values)


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value).replace(",", "").replace("$", ""))
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def pet_policy(value: Any) -> str:
    text = str(value or "").strip().lower()
    if re.search(r"\b(no pets|pets (?:not allowed|prohibited)|no dogs|no cats)\b", text):
        return "no"
    if re.search(r"\b(?:pets? friendly|pet-friendly|pets? (?:allowed|welcome)|cats?,? dogs? ok|yes)\b", text):
        return "yes"
    return "unknown"


def eligible(row: dict[str, Any], constraints: Constraints) -> bool:
    for key, field, compare in (
        ("rent_lt", "price_num", lambda a, b: a < b),
        ("rent_lte", "price_num", lambda a, b: a <= b),
        ("min_sqft", "sqft_num", lambda a, b: a >= b),
        ("min_beds", "beds_num", lambda a, b: a >= b),
        ("min_baths", "baths_num", lambda a, b: a >= b),
        ("max_transit_walk_minutes", "metro_min", lambda a, b: a <= b),
    ):
        bound = getattr(constraints, key)
        if bound is not None:
            actual = number(row.get(field))
            if actual is None or not compare(actual, bound):
                return False
            if field == "metro_min" and row.get("metro_travel_mode") != "walk":
                return False
    if constraints.exclude_floors:
        floor = number(row.get("floor"))
        if floor is None or floor in constraints.exclude_floors:
            return False
    if constraints.pet_friendly and pet_policy(row.get("pets_policy")) != "yes":
        return False
    if constraints.available_now and str(row.get("availability") or row.get("available_date") or "").lower() not in {"now", "available now", "immediately"}:
        return False
    return True


def filter_rows(rows: list[dict[str, Any]], constraints: Constraints) -> list[dict[str, Any]]:
    return [row for row in rows if eligible(row, constraints)]
