"""Account-backed Streamlit views; the API owns ranking, quotas and persistence."""

from __future__ import annotations

import uuid
import math
import hashlib
import json

import pandas as pd
import streamlit as st

from feature_access import capability, capabilities_from_features
from plan_ui import render_pricing_cards, render_upgrade_prompt
from shared.constraints import number


def api_call(client, method, path, payload=None, *, quiet=False, raw=False):
    pending = None
    fingerprint = None
    if isinstance(payload, dict) and "idempotency_key" in payload:
        intent = {key: value for key, value in payload.items() if key != "idempotency_key"}
        fingerprint = hashlib.sha256(json.dumps([method, path, intent], sort_keys=True).encode()).hexdigest()
        pending = st.session_state.setdefault("account_pending_requests", {})
        payload = {**payload, "idempotency_key": pending.setdefault(fingerprint, payload["idempotency_key"])}
    response = client.request(method, path, json=payload)
    if response.status_code not in {200, 201}:
        if not quiet:
            messages = {
                0: "Account services are temporarily unavailable.",
                401: "Please sign in again to continue.",
                403: "Your account does not include this feature.",
                409: "Your account limit has been reached or this request conflicts with existing data.",
                422: "Please check your inputs and try again.",
                429: "Your monthly allowance is exhausted. Please try again next period.",
                503: "This provider is unavailable. Your saved data is unchanged.",
            }
            st.error(messages.get(response.status_code, "Could not complete this request. Please try again."))
        return None
    if raw:
        if pending is not None:
            pending.pop(fingerprint, None)
        return response.text
    try:
        data = response.json()
        if pending is not None:
            pending.pop(fingerprint, None)
        return data
    except (ValueError, TypeError):
        if not quiet:
            st.error("The account service returned an unexpected response. Please try again.")
        return None


def hydrate_account(client):
    """Refresh authenticated data; never derive access from a preview selector."""
    entitlements = api_call(client, "GET", "/entitlements", quiet=True)
    properties = api_call(client, "GET", "/properties", quiet=True)
    profile = api_call(client, "GET", "/profile", quiet=True)
    if not all(isinstance(value, dict) for value in [entitlements, properties, profile]):
        st.session_state.pop("account_entitlements", None)
        st.session_state["account_properties"] = []
        st.session_state["user_profile"] = {}
        clear_comparison_downloads()
        return False
    features = entitlements.get("features", {})
    if features and "capabilities" not in entitlements:
        entitlements["capabilities"] = capabilities_from_features(features)
    limits = entitlements.get("limits", entitlements.get("quotas", {}))
    if "analyses" in limits:
        entitlements["quotas"] = {**limits, "monthly_analyses_limit": limits["analyses"], "saved_property_limit": limits["properties"]}
    st.session_state["account_entitlements"] = entitlements
    entitlements.setdefault("usage", {})["analyses_used"] = entitlements.get("usage", {}).get("analyses", 0)
    st.session_state["account_properties"] = [
        {**item.get("parsed", {}), **item} for item in properties.get("properties", [])
    ]
    st.session_state["user_profile"] = profile.get("preferences", {})
    return True


def clear_comparison_downloads():
    for key in ("account_export", "account_report", "account_export_scope", "account_analytics"):
        st.session_state.pop(key, None)


def reset_comparison_filters():
    st.session_state["account_filters"] = {}
    clear_comparison_downloads()
    # Deleting widget keys lets Streamlit rehydrate stale values from the browser.
    st.session_state.update({
        "account_filter_budget": 0,
        "account_filter_beds": 0,
        "account_filter_baths": 0.0,
        "account_filter_sqft": 0,
        "account_filter_request": "",
        "account_filter_manual_priorities": False,
        **{f"account_filter_priority_{priority}": 1.0
           for priority in ["price", "space", "commute", "walkability", "pets"]},
    })


def display_frame(frame):
    # st.dataframe has a built-in CSV download. A static table has no download UI.
    if capability("can_export"):
        st.dataframe(frame, width="stretch", hide_index=True)
    else:
        st.table(frame)


def number_label(value, noun):
    try:
        amount = float(value)
        if not math.isfinite(amount):
            return f"{noun.title()}s unknown"
        return f"{amount:g} {noun}" if amount == 1 else f"{amount:g} {noun}s"
    except (TypeError, ValueError):
        return f"{noun.title()}s unknown"


def listing_facts(item):
    """Flatten API records without changing their stored parsed payload."""
    return {**item.get("parsed", {}), **{key: value for key, value in item.items() if key != "parsed"}}


def fact_number(item, *keys):
    for key in keys:
        value = item.get(key)
        if key in {"beds", "bedrooms"} and str(value).strip().lower() == "studio":
            return 0.0
        parsed = number(value)
        if parsed is not None and parsed >= 0:
            return parsed
    return None


def room_summary(item, noun):
    """Apartment summaries use known unit counts, not absent building totals."""
    item = listing_facts(item)
    keys = ("beds_num", "beds", "bedrooms") if noun == "bed" else ("baths_num", "baths", "bathrooms")
    values = [
        value for unit in item.get("units", [])
        if (value := fact_number(listing_facts(unit), *keys)) is not None
    ]
    if not values:
        return number_label(fact_number(item, *keys), noun)
    low, high = min(values), max(values)
    return number_label(low, noun) if low == high else f"{low:g}–{high:g} {noun}s"


def listing_name(item):
    return next((str(item[key]) for key in
                 ("display_name", "property_title", "property", "address", "property_id", "id")
                 if item.get(key)), "Unnamed property")


def listing_label(item):
    unit = item.get("unit") or item.get("unit_number") or item.get("unit_id")
    return f"{listing_name(item)} · {unit}" if unit else listing_name(item)


def readable_listing_rows(rows):
    """Create a display-only projection; retain backend order and identities."""
    return [{
        "Rank": row.get("rank"),
        "Property": listing_name(row),
        "Unit": row.get("unit") or row.get("unit_number") or row.get("unit_id") or "Home",
        "Price type": "Purchase" if row.get("price_kind") == "purchase" or row.get("kind") == "home" else "Monthly rent",
        "Price ($)": fact_number(row, "price_num", "sale_price", "monthly_rent", "rent_price", "price", "unit_price"),
        "Square feet": fact_number(row, "sqft_num", "square_feet", "sqft", "unit_sqft"),
        "Bedrooms": number_label(fact_number(row, "beds_num", "beds", "bedrooms"), "bed"),
        "Bathrooms": number_label(fact_number(row, "baths_num", "baths", "bathrooms"), "bath"),
        "Monthly total ($)": number(row.get("monthly_total")),
        "Score": number(row.get("score")),
        "Confidence": f"{number(row['confidence']):.0%}" if number(row.get("confidence")) is not None else "Unknown",
    } for row in rows]


def render_listing_preview(parsed):
    item = listing_facts(parsed)
    st.subheader("Parsed listing preview")
    st.write(listing_name(item))
    if item.get("address"):
        st.caption(item["address"])
    columns = st.columns(3)
    columns[0].metric("Bedrooms", room_summary(item, "bed"))
    columns[1].metric("Bathrooms", room_summary(item, "bath"))
    units = item.get("units", [])
    columns[2].metric("Parsed units", len(units))
    if units:
        st.caption("Bedroom and bathroom ranges reflect known unit values; missing unit facts remain unknown.")
        st.markdown("#### Available units")
        unit_rows = [{**item, **listing_facts(unit)} for unit in units]
        table = pd.DataFrame(readable_listing_rows(unit_rows))
        table["Floor plan"] = [row.get("floorplan") or "Unknown" for row in unit_rows]
        table["Availability"] = [row.get("availability") or row.get("available_date") or "Unknown" for row in unit_rows]
        display_frame(table[["Unit", "Floor plan", "Price ($)", "Square feet", "Bedrooms", "Bathrooms", "Availability"]].fillna("Unknown"))
    else:
        price = fact_number(item, "sale_price", "monthly_rent", "rent_price", "price_num")
        area = fact_number(item, "square_feet", "sqft_num", "sqft")
        columns = st.columns(2)
        columns[0].metric("Purchase price" if item.get("sale_price") is not None else "Monthly rent",
                          f"${price:,.0f}" if price is not None else "Unknown")
        columns[1].metric("Square feet", f"{area:g}" if area is not None else "Unknown")
    facts = [{"Detail": label, "Value": str(item[key])} for key, label in [
        ("property_type", "Listing type"), ("pets_policy", "Pet policy"),
        ("availability", "Availability"), ("available_date", "Available date"),
        ("description", "Description"),
    ] if item.get(key) is not None and item.get(key) != ""]
    if facts:
        display_frame(pd.DataFrame(facts))
    amenities = [{"Amenity": key[4:].replace("_", " ").title(),
                  "Status": "Yes" if value is True else "No" if value is False else "Unknown"}
                 for key, value in item.items() if key.startswith("has_")]
    if amenities:
        with st.expander("Amenities"):
            display_frame(pd.DataFrame(amenities))
    for warning in item.get("warnings", []):
        st.warning(warning)


def render_tradeoffs(comparison):
    for key, label in [("advantages", "Strengths"), ("compromises", "Tradeoffs"), ("unknowns", "Unknown facts")]:
        st.markdown(f"#### {label}")
        entries = comparison.get(key, [])
        if entries:
            for entry in entries:
                st.write(f"• {entry}")
        else:
            st.caption("None identified from known facts.")


def render_score_components(components):
    display_frame(pd.DataFrame([{
        "Priority": key.title(), "Known fact": "Yes" if value.get("known") else "No — neutral assumption",
        "Value": value.get("value") if value.get("value") is not None else "Unknown",
        "Weight": value.get("weight"), "Score contribution": value.get("contribution"),
    } for key, value in components.items()]))


def render_ranked_summary(comparison):
    rows = comparison.get("ranked", [])
    if not rows:
        st.info("No eligible listings in this snapshot.")
        return
    winner = rows[0]
    with st.container(border=True):
        st.markdown("#### Top recommendation")
        st.write(listing_label(winner))
        columns = st.columns(3)
        score, confidence = number(winner.get("score")), number(winner.get("confidence"))
        columns[0].metric("Decision score", f"{score:.1f}/100" if score is not None else "Unknown")
        columns[1].metric("Known-input confidence", f"{confidence:.0%}" if confidence is not None else "Unknown")
        columns[2].metric("Eligible listings", len(rows))
        st.caption(f"{room_summary(winner, 'bed')} · {room_summary(winner, 'bath')}")
        if winner.get("comparison"):
            st.caption("Compared with the next-ranked alternative")
            render_tradeoffs(winner["comparison"])
        for preference in winner.get("unmet_preferences", []):
            st.warning(preference)
    st.markdown("#### Ranked listings")
    display_frame(pd.DataFrame(readable_listing_rows(rows)).fillna("Unknown"))
    for warning in comparison.get("warnings", []):
        st.caption(warning)
    if winner.get("components"):
        with st.expander("Recommendation score breakdown"):
            render_score_components(winner["components"])


def render_analytics(analytics):
    st.subheader("Advanced analytics")
    render_ranked_summary(analytics.get("baseline", {}))
    st.markdown("#### Priority sensitivity")
    st.caption("Each scenario increases one priority weight; a different winner indicates a priority-sensitive decision.")
    scenarios = [{
        "Priority increased": scenario.get("priority", "").title(),
        "Recommended listing": listing_label(scenario["winner"]) if scenario.get("winner") else "No eligible listing",
        "Winner score": number(scenario["winner"].get("score")) if scenario.get("winner") else None,
    } for scenario in analytics.get("sensitivity", [])]
    if scenarios:
        frame = pd.DataFrame(scenarios)
        display_frame(frame.fillna("Unknown"))
        chart = frame.dropna(subset=["Winner score"])
        if not chart.empty:
            st.bar_chart(chart.set_index("Priority increased")[["Winner score"]])
    else:
        st.info("No sensitivity scenarios available.")


def render_decision_report(report):
    st.subheader("Decision report")
    try:
        snapshot = json.loads(report["content"])
    except (KeyError, TypeError, ValueError):
        st.warning("The report preview is unavailable. The original report download is unchanged.")
        return
    if not isinstance(snapshot, dict):
        st.warning("The report preview is unavailable. The original report download is unchanged.")
        return
    st.caption(f"Report level: {str(snapshot.get('report_level', 'premium')).title()}")
    render_ranked_summary(snapshot.get("comparison", {}))
    if snapshot.get("analytics"):
        render_analytics(snapshot["analytics"])
    st.caption(snapshot.get("disclaimer", "Listing facts and decision scores are not independent verification."))


def render_advisor(client):
    if not st.session_state.get("auth_token"):
        st.caption("Sign in to use your account features.")
        return
    if not capability("can_use_ai_chat"):
        render_upgrade_prompt("can_use_ai_chat", "AI advisor")
        return
    for message in st.session_state.get("advisor_messages", []):
        with st.chat_message(message["role"]):
            st.write(message["content"])
    with st.form("account_advisor"):
        prompt = st.text_input("Ask about your saved properties")
        submit = st.form_submit_button("Ask advisor")
    if submit and prompt.strip():
        ids = [item["id"] for item in st.session_state.get("account_properties", []) if not item.get("is_archived")]
        reply = api_call(client, "POST", "/advisor", {
            "question": prompt.strip(), "idempotency_key": str(uuid.uuid4()), "property_ids": ids,
        })
        if reply is not None:
            messages = st.session_state.setdefault("advisor_messages", [])
            messages.extend([
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": reply.get("answer", "")},
            ])
            st.rerun()
    if st.session_state.get("advisor_messages") and st.button("Clear conversation"):
        st.session_state["advisor_messages"] = []
        st.rerun()


def render_preferences(client):
    prefs = st.session_state.get("user_profile", {})
    with st.form("account_preferences"):
        max_budget = st.number_input("Max monthly budget ($)", min_value=0, value=int(prefs.get("max_budget") or 0), step=50)
        beds = st.selectbox("Preferred bedrooms", [None, 0, 1, 2, 3, 4], index=[None, 0, 1, 2, 3, 4].index(prefs.get("preferred_beds")) if prefs.get("preferred_beds") in [None, 0, 1, 2, 3, 4] else 0, format_func=lambda v: "Any" if v is None else "Studio" if v == 0 else number_label(v, "bed"))
        sqft = st.number_input("Min square footage", min_value=0, value=int(prefs.get("min_sqft") or 0), step=25)
        pet_options = ["No preference", "Yes", "No"]
        pets = st.selectbox("Pet-friendly preference", pet_options, index=pet_options.index(prefs.get("pets", "No preference")) if prefs.get("pets", "No preference") in pet_options else 0)
        commute = st.number_input("Max commute (minutes)", min_value=0, value=int(prefs.get("commute_tolerance") or 30))
        destination = st.text_input("Commute destination", value=prefs.get("commute_destination", ""))
        mode = st.selectbox("Commute mode", ["driving", "transit", "walking", "bicycling"], index=["driving", "transit", "walking", "bicycling"].index(prefs.get("commute_mode", "driving")) if prefs.get("commute_mode", "driving") in ["driving", "transit", "walking", "bicycling"] else 0)
        submit = st.form_submit_button("Save preferences")
    if submit:
        updated = {**prefs, "max_budget": max_budget or None, "preferred_beds": beds,
                   "min_sqft": sqft or None, "commute_tolerance": commute,
                   "commute_destination": destination, "commute_mode": mode, "pets": pets}
        if api_call(client, "PUT", "/profile", {"preferences": updated}) is not None:
            st.session_state["user_profile"] = updated
            st.success("Preferences saved to your account.")


def render_profile(client, auth):
    st.title("Your account")
    account, subscription, preferences = st.tabs(["Account", "Subscription & Pricing", "Preferences"])
    with account:
        user = auth.user() or {}
        st.write(user.get("email", ""))
        with st.form("account_profile"):
            name = st.text_input("Display name", value=user.get("display_name", ""))
            submitted = st.form_submit_button("Save profile")
        if submitted:
            updated = api_call(client, "PATCH", "/profile", {"display_name": name})
            if updated is not None:
                st.session_state["auth_user"] = {**user, "display_name": name}
                st.success("Profile saved.")
        entitlements = st.session_state.get("account_entitlements", {})
        st.write("Plan:", entitlements.get("plan", "free").replace("_", " ").title())
        display_frame(pd.DataFrame([entitlements.get("quotas", {})]))
        if entitlements.get("legacy_credits") is not None:
            st.write("Preserved legacy credits:", entitlements["legacy_credits"])
            st.caption("Legacy credits are separate from monthly allowances and are not converted by the frontend.")
        st.caption("Account records persist after sign-in. This browser session is not permanent authentication.")
    with subscription:
        status = api_call(client, "GET", "/billing/status", quiet=True)
        if status:
            st.write("Subscription status:", status.get("subscription_status", "unknown"))
        if st.button("Refresh payment status"):
            auth.restore_from_session()
            st.rerun()
        if (status or {}).get("active_plan") in {"premium", "premium_plus"} and st.button("Manage subscription"):
            portal = api_call(client, "POST", "/billing/portal", {})
            if portal and portal.get("portal_url"):
                st.link_button("Open secure billing portal", portal["portal_url"])
        render_pricing_cards(client)
    with preferences:
        render_preferences(client)


def render_add_listing(client, screen):
    with st.expander("Add a listing", expanded=True):
        with st.form("account_add_listing"):
            listing_type = st.selectbox("Listing type", ["apartment", "rental_home", "home"], index=0 if screen == "Apartment Search" else 1, format_func=lambda kind: {"apartment": "Apartment", "rental_home": "Rental house", "home": "House for sale"}[kind])
            text = st.text_area("Paste listing text", height=180)
            save = st.form_submit_button("Parse listing")
        if save:
            if not text.strip():
                st.warning("Paste a listing before saving.")
            else:
                result = api_call(client, "POST", "/analyses", {
                    "text": text, "kind": listing_type, "idempotency_key": str(uuid.uuid4()),
                })
                if result is not None:
                    st.session_state["account_pending_listing"] = result
        pending = st.session_state.get("account_pending_listing")
        if pending:
            render_listing_preview(pending["parsed"])
            if st.button("Save parsed property"):
                saved = api_call(client, "POST", "/properties", {
                    "kind": pending["kind"], "parsed": pending["parsed"], "idempotency_key": str(uuid.uuid4()),
                })
                if saved is not None:
                    st.session_state.pop("account_pending_listing", None)
                    st.success("Listing saved to your account.")
                    st.rerun()


def render_property_controls(client, properties):
    if not properties:
        return
    st.subheader("Manage saved properties")
    options = {item["id"]: item for item in properties}
    selected = st.selectbox("Property", list(options), format_func=lambda key: options[key].get("display_name") or options[key].get("property_title") or options[key].get("property") or options[key].get("address") or str(key))
    item = options[selected]
    st.caption(f"{room_summary(item, 'bed')} · {room_summary(item, 'bath')}")
    with st.form("property_fees"):
        fees = item.get("fees", {})
        st.caption("Monthly recurring fees apply only to this property.")
        fields = {}
        for key, label in [("parking", "Parking"), ("utilities", "Utilities"), ("pet_fee", "Pet fee"), ("renters_insurance", "Renters insurance"), ("other", "Other monthly fees")]:
            value = fees.get(key)
            fields[key] = st.number_input(f"{label} ($/month)", min_value=0.0, value=float(value) if value is not None else None,
                                          step=5.0, placeholder="Unknown", key=f"property_fee_{selected}_{key}")
        save = st.form_submit_button("Save property fees")
    if save and api_call(client, "PATCH", f"/properties/{selected}", {"fees": fields}) is not None:
        st.rerun()
    if st.button("Archive property"):
        if api_call(client, "POST", f"/properties/{selected}/archive", {}) is not None:
            st.rerun()
    if capability("can_use_neighborhood_enrichment") and st.button("Enrich neighborhood"):
        result = api_call(client, "POST", "/enrichment", {"property_ids": [selected], "idempotency_key": str(uuid.uuid4())})
        if result is not None:
            st.write(result)
    if capability("can_use_commute_analysis"):
        with st.form("property_commute"):
            destination = st.text_input("Destination", value=st.session_state.get("user_profile", {}).get("commute_destination", ""))
            mode = st.selectbox("Travel mode", ["driving", "transit", "walking", "bicycling"])
            submit = st.form_submit_button("Calculate commute")
        if submit and destination.strip():
            result = api_call(client, "POST", "/commute", {"property_ids": [selected], "destination": destination, "mode": mode, "idempotency_key": str(uuid.uuid4())})
            if result is not None:
                st.write(result)
    if capability("can_use_ai_negotiation") and st.button("Generate negotiation guidance"):
        result = api_call(client, "POST", "/negotiation", {"property_ids": [selected], "question": "Draft a polite negotiation message grounded in confirmed facts for this property.", "idempotency_key": str(uuid.uuid4())})
        if result is not None:
            st.write(result.get("answer", result))


def render_comparison(client, properties):
    st.subheader("Saved comparison")
    st.caption("Apartments and houses share one saved-property allowance.")
    filters = st.session_state.setdefault("account_filters", {})
    with st.form("comparison_filters"):
        budget = st.number_input("Maximum rent ($/month)", min_value=0, value=int(filters.get("max_budget") or 0), key="account_filter_budget")
        beds = st.number_input("Minimum bedrooms", min_value=0, value=int(filters.get("min_beds") or 0), key="account_filter_beds")
        baths = st.number_input("Minimum bathrooms", min_value=0.0, value=float(filters.get("min_baths") or 0), step=0.5, key="account_filter_baths")
        sqft = st.number_input("Minimum square feet", min_value=0, value=int(filters.get("min_sqft") or 0), key="account_filter_sqft")
        request = st.text_input("Natural-language request", value=filters.get("request", ""), disabled=not capability("can_use_natural_language_filtering"), key="account_filter_request")
        priorities = {}
        manual_priorities = False
        if capability("can_use_lifestyle_score"):
            manual_priorities = st.checkbox(
                "Use manual priority weights instead of request priorities",
                value=bool(filters.get("manual_priorities", False)),
                key="account_filter_manual_priorities",
            )
            st.caption("Priority weights (0 ignores a priority; the backend normalizes the total).")
            for priority in ["price", "space", "commute", "walkability", "pets"]:
                priorities[priority] = st.slider(priority.title(), 0.0, 5.0, float(filters.get("priorities", {}).get(priority, 1.0)), 0.5, key=f"account_filter_priority_{priority}")
        apply = st.form_submit_button("Apply request and numeric filters")
    if apply:
        clear_comparison_downloads()
        st.session_state["account_filters"] = {"max_budget": budget or None, "min_beds": beds, "min_baths": baths, "min_sqft": sqft, "request": request.strip(), "priorities": priorities, "manual_priorities": manual_priorities}
        filters = st.session_state["account_filters"]
    if st.button("Reset filters", on_click=reset_comparison_filters):
        st.rerun()
    if filters:
        st.caption(f"Applied filters: {filters}")
    constraints = {key: value for key, value in filters.items() if key in {"min_beds", "min_baths", "min_sqft"} and value}
    if filters.get("max_budget"):
        constraints["rent_lte"] = filters["max_budget"]
    if filters.get("request"):
        parsed_request = api_call(client, "POST", "/requests", {"request": filters["request"]})
        if parsed_request is None:
            clear_comparison_downloads()
            return
        combined = dict(parsed_request.get("constraints", {}))
        for key, value in constraints.items():
            existing = combined.get(key)
            combine = max if key.startswith("min_") else min
            combined[key] = value if existing is None else combine(existing, value)
        constraints = combined
        priorities = (
            filters.get("priorities", {}) if filters.get("manual_priorities")
            else parsed_request.get("priorities") or filters.get("priorities", {})
        )
    else:
        priorities = filters.get("priorities", {})
    if priorities and sum(priorities.values()) <= 0:
        clear_comparison_downloads()
        st.warning("Choose at least one nonzero priority before applying.")
        return
    ids = [item["id"] for item in properties]
    comparison_inputs = {"property_ids": ids, "constraints": constraints, "priorities": priorities}
    st.caption(f"Applied constraints: {constraints or 'None'}")
    st.caption(f"Applied priorities: {priorities or 'Default priorities'}")
    if not ids:
        clear_comparison_downloads()
        st.info("Save a listing to begin your comparison.")
        return
    result = api_call(client, "POST", "/ranking", comparison_inputs)
    if result is None:
        clear_comparison_downloads()
        return
    rows = result.get("ranked", [])
    fingerprint = hashlib.sha256(json.dumps([comparison_inputs, rows], sort_keys=True).encode()).hexdigest()
    if fingerprint != st.session_state.get("account_comparison_fingerprint"):
        clear_comparison_downloads()
        st.session_state["account_comparison_fingerprint"] = fingerprint
    if not rows:
        st.info("No saved listings match these filters.")
        return
    frame = pd.DataFrame(rows)
    for key, noun in [("beds_num", "bed"), ("baths_num", "bath"), ("bathrooms", "bath"), ("baths", "bath")]:
        if key in frame:
            frame[key] = frame[key].apply(lambda value: number_label(value, noun))
    columns = [key for key in ["rank", "property", "unit", "price_kind", "price_num", "sqft_num", "beds_num",
                               "baths_num", "monthly_total", "commute_minutes", "score", "confidence"] if key in frame]
    display_frame(frame[columns] if columns else frame)
    selected_row = st.selectbox(
        "Listing details", list(range(len(rows))),
        format_func=lambda index: f"{rows[index].get('property') or rows[index].get('address') or rows[index].get('property_id')} · {rows[index].get('unit') or rows[index].get('unit_id') or 'Home'}",
    )
    detail = rows[selected_row]
    with st.expander("Decision details", expanded=False):
        st.write("Confidence:", detail.get("confidence", "Unknown"))
        st.write("Peer group:", detail.get("peer_group", "Unknown"))
        st.write("Comparable listings:", detail.get("peer_count", 0))
        if detail.get("comparison"):
            st.caption("Next-ranked alternative relative to this listing")
            st.write(detail["comparison"].get("compromise_summary", "Comparison unavailable"))
            render_tradeoffs(detail["comparison"])
        if capability("can_use_ai_explanations") and detail.get("components"):
            render_score_components(detail["components"])
    if capability("can_export"):
        scope = st.selectbox("CSV export scope", ["listings", "units", "properties"], format_func=lambda value: {
            "listings": "Visible comparison listings", "units": "Apartment units",
            "properties": "Property summaries (one matching listing per property)",
        }[value])
        if scope != st.session_state.get("account_export_scope"):
            st.session_state.pop("account_export", None)
        if st.button("Prepare CSV export"):
            exported = api_call(client, "POST", "/exports", {**comparison_inputs, "format": "csv", "scope": scope}, raw=True)
            if exported is not None:
                st.session_state["account_export"] = exported
                st.session_state["account_export_scope"] = scope
    if capability("can_export") and "account_export" in st.session_state:
        st.download_button("Download comparison CSV", st.session_state["account_export"], "nestai-comparison.csv", "text/csv")
    if capability("can_generate_ai_reports") and st.button("Generate decision report"):
        report = api_call(client, "POST", "/reports", {**comparison_inputs, "idempotency_key": str(uuid.uuid4())})
        if report is not None:
            st.session_state["account_report"] = report
    if capability("can_generate_ai_reports") and st.session_state.get("account_report"):
        report = st.session_state["account_report"]
        render_decision_report(report)
        if capability("can_export"):
            download = api_call(client, "GET", f"/reports/{report['report_id']}/download", raw=True)
            if download is not None:
                st.download_button("Download report", download, report["filename"], report["media_type"])
    entitlements = st.session_state.get("account_entitlements", {})
    if entitlements.get("plan") == "premium_plus" and st.button("View advanced analytics"):
        analytics = api_call(client, "POST", "/analytics", {"property_ids": ids, "constraints": constraints, "priorities": priorities, "idempotency_key": str(uuid.uuid4())})
        if analytics is not None:
            st.session_state["account_analytics"] = analytics
    if entitlements.get("plan") == "premium_plus" and st.session_state.get("account_analytics"):
        render_analytics(st.session_state["account_analytics"])


def render_account_view(client, auth, screen):
    if not auth.is_authenticated():
        st.info("Sign in to save and compare properties across sessions.")
        if st.button("Sign in", key="account_view_login"):
            st.session_state["main_nav"] = "Login"
            st.rerun()
        return
    if not st.session_state.get("account_entitlements"):
        st.warning("Account data could not be loaded. Please retry before making changes.")
        if st.button("Retry account loading"):
            st.rerun()
        return
    if st.session_state.get("show_feedback_form"):
        with st.form("account_feedback"):
            category = st.selectbox("Feedback category", ["bug", "feature_request", "improvement"])
            title = st.text_input("Feedback title")
            description = st.text_area("Describe the issue or suggestion")
            submitted = st.form_submit_button("Submit feedback")
        if submitted and title.strip():
            payload = {"category": {"bug": "bug", "feature_request": "feature", "improvement": "feedback"}[category],
                       "title": title, "description": description, "route_or_screen": screen,
                       "idempotency_key": str(uuid.uuid4())}
            result = api_call(client, "POST", "/feedback", payload)
            if result is not None:
                st.success(f"Feedback saved. Reference: {result.get('public_reference', '')}")
        if st.button("Close feedback"):
            st.session_state["show_feedback_form"] = False
            st.rerun()
    if screen == "Profile":
        render_profile(client, auth)
        return
    st.title("Compare your next home")
    render_add_listing(client, screen)
    properties = st.session_state.get("account_properties", [])
    active = [item for item in properties if not item.get("is_archived", False)]
    counts = st.columns(3)
    counts[0].metric("Saved properties", len(active))
    counts[1].metric("Apartment units", sum(len(item.get("units", [])) for item in active if item.get("kind") == "apartment"))
    counts[2].metric("Houses", sum(item.get("kind") in {"home", "rental_home"} for item in active))
    render_comparison(client, active)
    render_property_controls(client, active)
    archived = [item for item in properties if item.get("is_archived", False)]
    if archived:
        with st.expander("Archived properties"):
            for item in archived:
                st.write(item.get("name") or item.get("address") or item["id"])
                if st.button("Restore", key=f"restore_{item['id']}", disabled=not capability("can_restore_archived_property")):
                    if api_call(client, "POST", f"/properties/{item['id']}/restore", {}) is not None:
                        st.rerun()
    st.caption("Legacy session-owned house records are preserved locally, but are not automatically assigned to any account.")
