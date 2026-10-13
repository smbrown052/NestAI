"""Transactions serialize all writes on the account row (PostgreSQL FOR UPDATE)."""

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from uuid import uuid4, uuid5, NAMESPACE_URL

from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.auth.plans import current_plan
from app.db.models.user import User
from app.db.models.property import Property
from app.db.models.home_details import HomeDetails
from app.db.models.account import AccountProperty, AccountUnit, AccountPreference, MonthlyUsage, RequestReceipt
from shared.entitlements import limits_for, features_for
from shared.adapters import rank


def period():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def effective_plan(user):
    expires = user.beta_access_expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if user.beta_tester and (expires is None or expires > datetime.now(timezone.utc)):
        return "beta"
    plan = current_plan(user)
    if plan in {"premium", "premium_plus"} and user.subscription_status not in {"active", "trialing"}:
        return "free"
    return plan if plan in {"premium", "premium_plus"} else "free"


def limits(user):
    plan = effective_plan(user)
    return limits_for(plan, user.beta_limits if plan == "beta" else None)


def features(user):
    plan = effective_plan(user)
    return features_for(plan, user.beta_features if plan == "beta" else None)


def lock_account(db, user):
    return db.query(User).filter_by(id=user.id).populate_existing().with_for_update().one()


def gate(user, feature):
    if not features(user).get(feature):
        raise HTTPException(403, {"code": "plan_required", "feature": feature})


def consume(db, user, metric):
    cap = limits(user)[metric]
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


def active_property_count(db, user):
    return db.query(AccountProperty).filter(
        AccountProperty.user_id == user.id,
        AccountProperty.parsed["is_archived"].as_boolean().is_not(True),
    ).count()


def require_property_slot(db, user):
    cap = limits(user)["properties"]
    if active_property_count(db, user) >= cap:
        raise HTTPException(429, {"code": "property_limit", "limit": cap})


def save(db, user, payload):
    parsed = payload.parsed
    if "is_archived" in parsed and not isinstance(parsed["is_archived"], bool):
        raise HTTPException(422, "is_archived must be a boolean")
    if len(json.dumps(parsed, allow_nan=False)) > 500_000:
        raise HTTPException(413, "Parsed property is too large")
    identity = payload.external_id or hashlib.sha256(
        json.dumps({"kind": payload.kind, "parsed": parsed}, sort_keys=True).encode()
    ).hexdigest()
    row = db.query(AccountProperty).filter_by(user_id=user.id, external_id=identity).first()
    archived = parsed.get("is_archived", bool(row and row.parsed.get("is_archived")))
    if row and row.parsed.get("is_archived") and not archived:
        gate(user, "restore")
        require_property_slot(db, user)
    if not row:
        if not archived:
            require_property_slot(db, user)
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


def recover_legacy(db, user):
    recovered, existing = [], []
    for source in db.query(Property).filter(Property.user_id == user.id).order_by(Property.id):
        identity = f"legacy-property:{source.id}"
        previous = db.query(AccountProperty).filter_by(user_id=user.id, external_id=identity).first()
        if previous:
            existing.append(previous.id)
            continue
        parsed = {column.name: getattr(source, column.name) for column in source.__table__.columns
                  if column.name not in {"id", "user_id", "session_id", "created_at", "updated_at"}}
        details = db.query(HomeDetails).filter_by(property_id=source.id).first()
        if details:
            facts = {column.name: getattr(details, column.name) for column in details.__table__.columns
                     if column.name not in {"id", "property_id", "created_at", "updated_at"}}
            parsed.update(facts)
            parsed["legacy_home_details_id"] = details.id
        parsed["legacy_property_id"] = source.id
        parsed["ownership_provenance"] = "existing_postgres_properties.user_id"
        parsed["is_archived"] = bool(source.is_archived or source.status == "ARCHIVED")
        kind = ("rental_home" if source.property_type == "RENTAL_HOME" else
                "apartment" if source.property_type.startswith("APARTMENT") else "home")
        row = AccountProperty(
            id=str(uuid5(NAMESPACE_URL, f"nestai:user:{user.id}:{identity}")),
            user_id=user.id, external_id=identity, kind=kind, parsed=parsed,
            created_at=source.created_at, updated_at=source.updated_at,
        )
        db.add(row)
        recovered.append(row.id)
    db.flush()
    return {"recovered_property_ids": recovered, "already_recovered_property_ids": existing,
            "policy": "Only pre-existing explicit PostgreSQL user_id ownership is recovered. Shared/null-owned caches are never claimed.",
            "quota_policy": "Existing owned records are preserved even above current caps; new saves remain capped."}


def numeric(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace("$", "").replace(",", ""))
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def first_numeric(*values):
    return next((number for value in values if (number := numeric(value)) is not None), None)


def ranking(db, user, ids, constraints, priorities):
    if priorities:
        gate(user, "lifestyle")
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
                   "price_num": first_numeric(
                       values.get("sale_price") if prop.kind == "home" else None,
                       values.get("price_num"), values.get("price"), values.get("rent_price"), values.get("monthly_rent")),
                   "sqft_num": first_numeric(values.get("sqft_num"), values.get("sqft"), values.get("square_feet")),
                   "beds_num": first_numeric(values.get("beds_num"), values.get("beds"), values.get("bedrooms")),
                   "baths_num": first_numeric(values.get("baths_num"), values.get("baths"), values.get("bathrooms")),
                   "commute_minutes": first_numeric(values.get("commute_minutes"), values.get("commute_transit_min"))}
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


def advice_context(db, user, payload):
    selected = properties(db, user, payload.property_ids)
    comparison = ranking(db, user, payload.property_ids, payload.constraints, payload.priorities)
    if not comparison["ranked"]:
        raise HTTPException(422, "No eligible saved options match these constraints")
    fields = {"property_id", "unit_id", "property", "unit", "kind", "price_num", "sqft_num", "beds_num", "baths_num",
              "score", "confidence", "components", "comparison", "monthly_total", "fees_complete", "walk_score",
              "commute_minutes", "peer_group", "peer_count", "peer_average", "pets_policy", "unmet_preferences"}
    profile = db.get(AccountPreference, user.id)
    preferences = profile.preferences if profile else {}
    verified = {}
    for receipt in db.query(RequestReceipt).filter_by(user_id=user.id, operation="enrichment").order_by(
        RequestReceipt.created_at.desc()
    ).limit(100):
        response = receipt.response
        property_id = response.get("property_id")
        if property_id in payload.property_ids and property_id not in verified and (
            response.get("status") == "complete" and not response.get("mock")
        ):
            verified[property_id] = response
    return {
        "ranked": [{key: value for key, value in row.items() if key in fields} for row in comparison["ranked"]],
        "profile": {"pets": preferences.get("pets") if preferences.get("pets") in {"Yes", "No", "No preference"} else "No preference",
                    "max_budget": numeric(preferences.get("max_budget"))},
        "constraints": payload.constraints, "priorities": payload.priorities,
        "neighborhood": [{"property_id": row.id, "enrichment": verified.get(row.id)} for row in selected],
        "warning": "Listing facts are user-supplied. Provider facts retain source timestamps. Neutral components are not verified facts.",
    }


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
    if scope == "listings":
        return ranked
    if scope == "units":
        return [row for row in ranked if row.get("unit_id") is not None]
    result, seen = [], set()
    for row in ranked:
        if row["property_id"] not in seen:
            result.append(row)
            seen.add(row["property_id"])
    return result


def ranked_snapshots(selected, ranked):
    eligible = {}
    for row in ranked:
        eligible.setdefault(row["property_id"], []).append(row.get("unit_id"))
    records = {record["id"]: record for record in selected}
    snapshots = []
    for property_id, unit_ids in eligible.items():
        record = records[property_id]
        saved_units = {unit["id"]: unit for unit in record["units"]}
        units = [saved_units[unit_id] for unit_id in dict.fromkeys(unit_ids) if unit_id in saved_units]
        parsed = dict(record["parsed"])
        if "units" in parsed:
            parsed["units"] = units
        snapshots.append({**record, "parsed": parsed, "units": units})
    return snapshots


def csv_export(rows, scope):
    output = io.StringIO(newline="")
    if scope == "listings":
        columns = ["rank", "property_id", "unit_id", "kind", "name", "price_kind", "price", "beds", "baths",
                   "square_feet", "score", "monthly_total", "fees_complete"]
    elif scope == "units":
        columns = ["property_id", "unit_id", "beds", "baths", "rent", "square_feet", "score", "monthly_total", "fees_complete"]
    else:
        columns = ["property_id", "kind", "name", "address", "monthly_rent", "sale_price", "bedrooms", "bathrooms",
                   "square_feet", "score", "monthly_total", "fees_complete"]
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        if scope == "listings":
            writer.writerow([row.get("rank"), safe_cell(row["property_id"]), safe_cell(row.get("unit_id")),
                             safe_cell(row.get("kind")), safe_cell(row.get("property")), safe_cell(row.get("price_kind")),
                             *[numeric(row.get(key)) if numeric(row.get(key)) is not None else ""
                               for key in ("price_num", "beds_num", "baths_num", "sqft_num", "score", "monthly_total")],
                             row.get("fees_complete", False)])
        elif scope == "units":
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
