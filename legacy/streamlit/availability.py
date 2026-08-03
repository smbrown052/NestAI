from __future__ import annotations

from datetime import date, datetime, timedelta


def availability_label(value: object) -> str:
    raw = str(value or "").strip()
    return raw or "Unknown"


def parse_availability_date(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    lowered = raw.lower()
    if lowered in {"unknown", "n/a", "na", "—", "-"}:
        return None
    if lowered in {"now", "available now", "immediately", "immediate"}:
        return datetime.combine(date.today(), datetime.min.time())

    today = date.today()
    cleaned = raw.replace(",", "")
    for fmt in ("%b %d %Y", "%B %d %Y", "%b %d", "%B %d", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            if "%Y" not in fmt:
                parsed = parsed.replace(year=today.year)
                if parsed.date() < today - timedelta(days=30):
                    parsed = parsed.replace(year=today.year + 1)
            return parsed
        except ValueError:
            continue
    return None


def availability_matches(value: object, mode: str, selected_date: date | None = None) -> bool:
    if mode == "Flexible / no preference":
        return True

    parsed = parse_availability_date(value)
    if parsed is None:
        return True

    today = date.today()
    available_on = parsed.date()
    if mode == "Available now":
        return available_on <= today
    if mode == "Available by selected date" and selected_date is not None:
        return available_on <= selected_date
    return True
