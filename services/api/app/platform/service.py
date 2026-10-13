"""Transactions serialize all writes on the account row (PostgreSQL FOR UPDATE)."""

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.auth.plans import current_plan
from app.db.models.user import User
from app.db.models.account import AccountProperty, AccountUnit, AccountPreference, MonthlyUsage, RequestReceipt
from shared.entitlements import limits_for, features_for
from shared.adapters import rank


def period():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def effective_plan(user):
    plan = current_plan(user)
    if plan in {"premium", "premium_plus"} and user.subscription_status not in {"active", "trialing"}:
        return "free"
    return plan if plan in {"premium", "premium_plus"} else "free"


def lock_account(db, user):
    return db.query(User).filter_by(id=user.id).populate_existing().with_for_update().one()


def gate(user, feature):
    if not features_for(effective_plan(user)).get(feature):
        raise HTTPException(403, {"code": "plan_required", "feature": feature})


def consume(db, user, metric):
    cap = limits_for(effective_plan(user))[metric]
    month = period()
    row = db.get(MonthlyUsage, (user.id, month, metric))
    if not row:
        row = MonthlyUsage(user_id=user.id, period=month, metric=metric, count=0)
        db.add(row)
    if row.count >= cap:
        raise HTTPException(429, {"code": "quota_exhausted", "metric": metric, "limit": cap, "period": month})
    row.count += 1


def execute(db: Session, user: User, operation: str, payload, work, metric=None, feature=None):
    user = lock_account(db, user)
    if feature:
        gate(user, feature)
    data = payload.model_dump(mode="json")
    try:
        canonical = json.dumps(data, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        raise HTTPException(422, "Request must contain finite JSON values") from None
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    receipt = db.get(RequestReceipt, (user.id, payload.idempotency_key))
    if receipt:
        if receipt.operation != operation or receipt.fingerprint != fingerprint:
            raise HTTPException(409, "Idempotency key already used for different input")
        return receipt.response
    try:
        if metric:
            consume(db, user, metric)
        response = work(user)
        db.add(RequestReceipt(user_id=user.id, key=payload.idempotency_key,
                              operation=operation, fingerprint=fingerprint, response=response))
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def properties(db, user, ids=None):
    query = db.query(AccountProperty).filter_by(user_id=user.id)
    if ids:
        ids = list(dict.fromkeys(ids))
        query = query.filter(AccountProperty.id.in_(ids))
    result = query.order_by(AccountProperty.created_at, AccountProperty.id).all()
    if ids and len(result) != len(ids):
        raise HTTPException(404, "Property not found")
    return result


def serialize(db, row):
    return {"id": row.id, "external_id": row.external_id, "kind": row.kind,
            "parsed": row.parsed,
            "fees": row.parsed.get("fees", {}),
            "is_archived": bool(row.parsed.get("is_archived", False)),
            "units": [{"id": unit.id, **{k: v for k, v in unit.parsed.items() if k != "id"}}
                      for unit in db.query(AccountUnit).filter_by(property_id=row.id).order_by(AccountUnit.id)],
            "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}


def save(db, user, payload):
    parsed = payload.parsed
    if len(json.dumps(parsed, allow_nan=False)) > 500_000:
        raise HTTPException(413, "Parsed property is too large")
    identity = payload.external_id or hashlib.sha256(
        json.dumps({"kind": payload.kind, "parsed": parsed}, sort_keys=True).encode()
    ).hexdigest()
    row = db.query(AccountProperty).filter_by(user_id=user.id, external_id=identity).first()
    if not row:
        count = db.query(AccountProperty).filter_by(user_id=user.id).count()
        cap = limits_for(effective_plan(user))["properties"]
        if count >= cap:
            raise HTTPException(429, {"code": "property_limit", "limit": cap})
        row = AccountProperty(id=str(uuid4()), user_id=user.id, external_id=identity,
                              kind=payload.kind, parsed=parsed)
        db.add(row)
        db.flush()
    row.kind, row.parsed = payload.kind, {**row.parsed, **parsed}
    row.updated_at = datetime.now(timezone.utc)
    if "units" not in parsed:
        db.flush()
        return serialize(db, row)
    units = parsed.get("units", [])
    if not isinstance(units, list) or len(units) > 1000:
        raise HTTPException(422, "units must be an array of at most 1000 objects")
    normalized = []
    seen = set()
    for unit in units:
        if not isinstance(unit, dict):
            raise HTTPException(422, "Each unit must be an object")
        unit_id = unit.get("id", unit.get("unit_number", unit.get("unit_label", unit.get("unit"))))
        if unit_id is None:
            raise HTTPException(422, "Every unit needs a string id or unit_number")
        # Numeric IDs lose leading zeroes before reaching us, so refuse them.
        if not isinstance(unit_id, str) or not unit_id or len(unit_id) > 128 or unit_id in seen:
            raise HTTPException(422, "Unit ids must be unique nonempty strings (max 128 characters)")
        seen.add(unit_id)
        normalized.append((unit_id, unit))
    existing = {unit.id: unit for unit in db.query(AccountUnit).filter_by(property_id=row.id)}
    for unit_id, unit in existing.items():
        if unit_id not in seen:
            unit.parsed = {**unit.parsed, "is_archived": True}
    for unit_id, unit in normalized:
        if unit_id in existing:
            existing[unit_id].parsed = {**existing[unit_id].parsed, **unit,
                                        "is_archived": unit.get("is_archived", False)}
        else:
            db.add(AccountUnit(property_id=row.id, id=unit_id, parsed=unit))
    db.flush()
    return serialize(db, row)


def numeric(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace("$", "").replace(",", ""))
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def ranking(db, user, ids, constraints, priorities):
    rows = decision_rows(db, user, ids)
    profile = db.get(AccountPreference, user.id)
    try:
        ranked = rank(rows, priorities or None, constraints, profile.preferences if profile else {})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"ranked": ranked, "method": "shared_decision",
            "warnings": ["Unknown inputs are labeled and receive a neutral contribution; scores are decision aids, not verified facts."]}


def decision_rows(db, user, ids):
    rows = []
    for prop in properties(db, user, ids):
        if prop.parsed.get("is_archived"):
            continue
        data = prop.parsed
        units = db.query(AccountUnit).filter_by(property_id=prop.id).order_by(AccountUnit.id).all()
        for unit in units or [None]:
            if unit and unit.parsed.get("is_archived"):
                continue
            values = {**{key: value for key, value in data.items() if key != "units"},
                      **(unit.parsed if unit else {})}
            for key in ("extra_parking", "extra_utilities", "extra_pet_fee", "extra_renters_insurance", "extra_other"):
                if key in data:
                    values[key] = data[key]
            if unit:
                values["price"] = values.get("price", values.get("unit_price"))
                values["sqft"] = values.get("sqft", values.get("unit_sqft"))
            row = {**values, "id": prop.id, "kind": prop.kind, "property_id": prop.id, "unit_id": unit.id if unit else None,
                   "property": values.get("display_name") or values.get("property_title") or values.get("address"),
                   "unit": unit.id if unit else "",
                   "price_num": numeric(values.get("price", values.get("rent_price", values.get("monthly_rent", values.get("sale_price"))))),
                   "sqft_num": numeric(values.get("sqft", values.get("square_feet"))),
                   "beds_num": numeric(values.get("beds_num", values.get("beds", values.get("bedrooms")))),
                   "baths_num": numeric(values.get("baths_num", values.get("baths", values.get("bathrooms")))),
                   "commute_minutes": numeric(values.get("commute_minutes", values.get("commute_transit_min")))}
            rows.append(row)
    return rows


def analytics(db, user, ids, constraints, priorities):
    from shared.decision import sensitivity
    baseline = ranking(db, user, ids, constraints, priorities)
    profile = db.get(AccountPreference, user.id)
    try:
        scenarios = sensitivity(decision_rows(db, user, ids), priorities or None,
                                constraints, profile.preferences if profile else {})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"baseline": baseline, "sensitivity": scenarios, "method": "shared_decision_sensitivity"}


def safe_cell(value):
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        value = json.dumps(value, sort_keys=True)
    text = str(value)
    # Spreadsheet engines may ignore whitespace/control prefixes.
    if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def export_rows(ranked, scope):
    if scope == "units":
        return [row for row in ranked if row.get("unit_id") is not None]
    result, seen = [], set()
    for row in ranked:
        if row["property_id"] not in seen:
            result.append(row)
            seen.add(row["property_id"])
    return result


def csv_export(rows, scope):
    output = io.StringIO(newline="")
    columns = (["property_id", "unit_id", "beds", "baths", "rent", "square_feet", "score", "monthly_total", "fees_complete"]
               if scope == "units" else
               ["property_id", "kind", "name", "address", "monthly_rent", "sale_price", "bedrooms", "bathrooms", "square_feet",
                "score", "monthly_total", "fees_complete"])
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        if scope == "units":
            writer.writerow([safe_cell(row["property_id"]), safe_cell(row["unit_id"]),
                             *[numeric(row.get(key)) if numeric(row.get(key)) is not None else ""
                               for key in ("beds_num", "baths_num", "price_num", "sqft_num", "score", "monthly_total")],
                             row.get("fees_complete", False)])
        else:
            writer.writerow([safe_cell(row["property_id"]), safe_cell(row.get("kind")),
                             safe_cell(row.get("property")), safe_cell(row.get("address")),
                             *[numeric(value) if numeric(value) is not None else "" for value in (
                                 row.get("price_num") if row.get("kind") != "home" else row.get("monthly_rent"),
                                 row.get("sale_price"), row.get("beds_num"), row.get("baths_num"), row.get("sqft_num"),
                                 row.get("score"), row.get("monthly_total"))],
                             row.get("fees_complete", False)])
    return output.getvalue()
