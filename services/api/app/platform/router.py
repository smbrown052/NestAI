import hashlib
import json
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from app.auth.dependencies import get_current_user
from app.db.models.user import User
from app.db.models.account import AccountProperty, AccountUnit, AccountPreference, MonthlyUsage, RequestReceipt
from app.db.models.credits import CreditBalance
from app.db.models.feedback import FeedbackReport
from app.db.session import get_db
from app.platform import schemas, service, providers
from shared.adapters import parse_listing
from shared.entitlements import limits_for, features_for

router = APIRouter(tags=["account platform"])


@router.get("/entitlements")
def entitlements(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    plan = service.effective_plan(user)
    usage = {row.metric: row.count for row in db.query(MonthlyUsage).filter_by(user_id=user.id, period=service.period())}
    usage["properties"] = db.query(AccountProperty).filter_by(user_id=user.id).count()
    balance = db.query(CreditBalance).filter_by(user_id=user.id).first()
    return {"plan": plan, "period": service.period(), "timezone": "UTC",
            "limits": limits_for(plan), "usage": usage, "features": features_for(plan),
            "legacy_credits": {"remaining": balance.credits_remaining, "purchased": balance.credits_purchased} if balance else None,
            "legacy_credits_policy": "Preserved separately; not converted into monthly quotas."}


@router.get("/profile")
def profile(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.get(AccountPreference, user.id)
    return {"preferences": row.preferences if row else {}}


@router.put("/profile")
def update_profile(payload: schemas.Profile, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service.lock_account(db, user)
    try:
        serialized = json.dumps(payload.preferences, allow_nan=False)
    except (TypeError, ValueError):
        raise HTTPException(422, "Preferences must contain finite JSON values") from None
    if len(serialized) > 30_000:
        raise HTTPException(413, "Preferences too large")
    row = db.get(AccountPreference, user.id)
    if not row:
        row = AccountPreference(user_id=user.id, preferences=payload.preferences)
        db.add(row)
    row.preferences = payload.preferences
    db.commit()
    return {"preferences": row.preferences}


@router.patch("/profile")
def patch_profile(payload: schemas.ProfilePatch, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    user = service.lock_account(db, user)
    user.display_name = payload.display_name.strip() or None
    db.commit()
    return {"display_name": user.display_name}


@router.post("/requests")
def natural_request(payload: schemas.NaturalRequest, user: User = Depends(get_current_user)):
    from shared.constraints import parse_constraints, ConstraintError
    try:
        constraints = parse_constraints(payload.request)
    except ConstraintError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"constraints": constraints.to_dict(), "priorities": {}, "summary": constraints.summary(),
            "method": "shared_deterministic_constraints"}


@router.post("/feedback")
def feedback(payload: schemas.Feedback, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    def work(account):
        if not payload.title.strip() or not payload.description.strip():
            raise HTTPException(422, "Feedback title and description must not be blank")
        row = FeedbackReport(
            public_reference="NA-" + uuid4().hex[:24], user_id=account.id,
            category=payload.category, title=payload.title.strip(), description=payload.description.strip(),
            actual_behavior=payload.actual_behavior, expected_behavior=payload.expected_behavior,
            route_or_screen=payload.route_or_screen, user_plan=service.effective_plan(account),
            beta_tester=account.beta_tester, user_contact_allowed=payload.user_contact_allowed,
            contact_email=account.email if payload.user_contact_allowed else None, status="new",
        )
        db.add(row)
        db.flush()
        return {"id": row.id, "public_reference": row.public_reference, "status": row.status}
    return service.execute(db, user, "feedback", payload, work)


@router.post("/analyses")
def analyse(payload: schemas.Analysis, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not payload.text.strip():
        raise HTTPException(422, "Listing text must not be blank")
    def parse(account):
        try:
            parsed = parse_listing(payload.text, payload.kind)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if payload.kind == "apartment":
            valid = bool(parsed.get("units"))
        else:
            expected = "HOME_FOR_SALE" if payload.kind == "home" else "RENTAL_HOME"
            price = service.numeric(parsed.get("sale_price" if payload.kind == "home" else "monthly_rent"))
            valid = bool(parsed.get("address")) and parsed.get("property_type") == expected and price is not None and price > 0
        if not valid:
            raise HTTPException(422, "No valid listing was parsed; no analysis quota was consumed")
        return {"kind": payload.kind, "parsed": parsed}
    return service.execute(db, user, "analyse", payload,
                           parse,
                           metric="analyses")


@router.get("/properties")
def list_properties(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"properties": [service.serialize(db, row) for row in service.properties(db, user)]}


@router.post("/properties")
def save_property(payload: schemas.SaveProperty, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.execute(db, user, "save", payload, lambda account: service.save(db, account, payload))


@router.delete("/properties/{property_id}")
def delete_property(property_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service.lock_account(db, user)
    row = service.properties(db, user, [property_id])[0]
    db.query(AccountUnit).filter_by(property_id=row.id).delete()
    db.delete(row)
    db.commit()
    return {"deleted": property_id}


@router.patch("/properties/{property_id}")
def patch_property(property_id: str, payload: schemas.PropertyPatch,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service.lock_account(db, user)
    row = service.properties(db, user, [property_id])[0]
    fees = {**row.parsed.get("fees", {}), **payload.fees.model_dump(exclude_unset=True)}
    row.parsed = {**row.parsed, "fees": fees, **{f"extra_{key}": value for key, value in fees.items()}}
    db.commit()
    return service.serialize(db, row)


def archive_property(property_id, archived, db, user):
    service.lock_account(db, user)
    row = service.properties(db, user, [property_id])[0]
    row.parsed = {**row.parsed, "is_archived": archived}
    db.commit()
    return service.serialize(db, row)


@router.post("/properties/{property_id}/archive")
def archive(property_id: str, payload: schemas.Empty,
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return archive_property(property_id, True, db, user)


@router.post("/properties/{property_id}/restore")
def restore(property_id: str, payload: schemas.Empty,
            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return archive_property(property_id, False, db, user)


@router.post("/ranking")
def ranking(payload: schemas.Ranking, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.ranking(db, user, payload.property_ids, payload.constraints, payload.priorities)


def records(db, user, payload):
    return [service.serialize(db, row) for row in service.properties(db, user, payload.property_ids)]


@router.post("/advisor")
def advisor(payload: schemas.PaidRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.execute(db, user, "advisor", payload,
                           lambda account: providers.advisor(records(db, account, payload), payload.question),
                           metric="ai", feature="advisor")


@router.post("/negotiation")
def negotiation(payload: schemas.PaidRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.execute(db, user, "negotiation", payload,
                           lambda account: providers.advisor(records(db, account, payload), payload.question, True),
                           metric="ai", feature="negotiation")


def address(record):
    value = record["parsed"].get("address")
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(422, "A confirmed property address is required")
    return value


@router.post("/enrichment")
def enrichment(payload: schemas.PaidRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    def work(account):
        selected = records(db, account, payload)
        if len(selected) != 1:
            raise HTTPException(422, "Enrichment requires exactly one property")
        result = {"property_id": selected[0]["id"], **providers.enrichment(address(selected[0]))}
        if not result.get("mock"):
            row = service.properties(db, account, [selected[0]["id"]])[0]
            row.parsed = {**row.parsed, "enrichment": result}
        return result
    return service.execute(db, user, "enrichment", payload, work, metric="enrichment", feature="enrichment")


@router.post("/commute")
def commute(payload: schemas.PaidRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    def work(account):
        selected = records(db, account, payload)
        if len(selected) != 1 or not payload.destination.strip():
            raise HTTPException(422, "Commute requires one property and a destination")
        result = {"property_id": selected[0]["id"], "destination": payload.destination, "mode": payload.mode,
                  **providers.commute(address(selected[0]), payload.destination, payload.mode)}
        if not result.get("mock"):
            row = service.properties(db, account, [selected[0]["id"]])[0]
            routes = result.get("routes") or []
            duration = service.numeric(routes[0].get("duration_seconds")) if routes else None
            row.parsed = {**row.parsed, "commute": result,
                          "commute_minutes": duration / 60 if duration is not None else None,
                          f"commute_{payload.mode}_min": duration / 60 if duration is not None else None}
        return result
    return service.execute(db, user, "commute", payload, work, metric="commute", feature="commute")


@router.post("/analytics")
def analytics(payload: schemas.PaidRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return service.execute(
        db, user, "analytics", payload,
        lambda account: service.analytics(db, account, payload.property_ids, payload.constraints, payload.priorities),
        feature="analytics",
    )


@router.post("/reports")
def report(payload: schemas.PaidRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    def work(account):
        selected = records(db, account, payload)
        comparison = service.ranking(db, account, payload.property_ids, payload.constraints, payload.priorities)
        report_id = hashlib.sha256(f"{account.id}:{payload.idempotency_key}".encode()).hexdigest()
        snapshot = {"properties": selected, "comparison": comparison,
                    "report_level": "plus" if service.effective_plan(account) == "premium_plus" else "premium",
                    "disclaimer": "Listing data and neutral score assumptions are not independent verification."}
        if service.effective_plan(account) == "premium_plus":
            snapshot["analytics"] = service.analytics(
                db, account, payload.property_ids, payload.constraints, payload.priorities
            )
        content = json.dumps(snapshot, sort_keys=True, indent=2, ensure_ascii=False)
        return {"report_id": report_id, "filename": f"nestai-report-{report_id[:12]}.json",
                "media_type": "application/json", "content": content,
                "download_url": f"/reports/{report_id}/download"}
    return service.execute(db, user, "reports", payload, work, metric="reports", feature="reports")


@router.get("/reports/{report_id}/download")
def download_report(report_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    service.gate(user, "reports")
    rows = db.query(RequestReceipt).filter_by(user_id=user.id, operation="reports")
    for row in rows:
        if row.response.get("report_id") == report_id:
            return Response(row.response["content"], media_type="application/json",
                            headers={"Content-Disposition": f'attachment; filename="{row.response["filename"]}"'})
    raise HTTPException(404, "Report not found")


@router.post("/exports")
def exports(payload: schemas.Export, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    user = service.lock_account(db, user)
    service.gate(user, "exports")
    ranked = service.ranking(db, user, payload.property_ids, payload.constraints, payload.priorities)["ranked"]
    selected = service.export_rows(ranked, payload.scope)
    if payload.format == "json":
        content = json.dumps(selected, sort_keys=True, ensure_ascii=False)
        media = "application/json"
    else:
        content = service.csv_export(selected, payload.scope)
        media = "text/csv"
    return Response(content, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="nestai-{payload.scope}.{payload.format}"'})
