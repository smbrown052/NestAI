"""Account-backed Streamlit views; the API owns ranking, quotas and persistence."""

from __future__ import annotations

import uuid
import math

import pandas as pd
import streamlit as st

from feature_access import capability
from plan_ui import render_pricing_cards, render_upgrade_prompt


def api_call(client, method, path, payload=None, *, quiet=False, raw=False):
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
        return response.text
    try:
        return response.json()
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
        return False
    features = entitlements.get("features", {})
    if features and "capabilities" not in entitlements:
        mapping = {
            "can_compare_multiple_properties": "basic_comparison",
            "can_use_ai_chat": "advisor",
            "can_use_natural_language_filtering": "advisor",
            "can_use_lifestyle_score": "advisor",
            "can_use_ai_explanations": "advisor",
            "can_use_google_apis": "enrichment",
            "can_use_neighborhood_enrichment": "enrichment",
            "can_use_walk_score_api": "enrichment",
            "can_use_commute_analysis": "commute",
            "can_use_ai_negotiation": "negotiation",
            "can_generate_ai_reports": "reports",
            "can_export": "exports",
            "can_restore_archived_property": "exports",
        }
        entitlements["capabilities"] = {key: features.get(source) is True for key, source in mapping.items()}
        entitlements["capabilities"].update(can_analyze_property=True, can_save_property=True, can_use_basic_filters=True)
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


def display_frame(frame):
    # st.dataframe has a built-in CSV download. A static table has no download UI.
    if capability("can_export"):
        st.dataframe(frame, use_container_width=True, hide_index=True)
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
        commute = st.number_input("Max commute (minutes)", min_value=0, value=int(prefs.get("commute_tolerance") or 30))
        destination = st.text_input("Commute destination", value=prefs.get("commute_destination", ""))
        mode = st.selectbox("Commute mode", ["driving", "transit", "walking", "bicycling"], index=["driving", "transit", "walking", "bicycling"].index(prefs.get("commute_mode", "driving")) if prefs.get("commute_mode", "driving") in ["driving", "transit", "walking", "bicycling"] else 0)
        submit = st.form_submit_button("Save preferences")
    if submit:
        updated = {**prefs, "max_budget": max_budget or None, "preferred_beds": beds,
                   "min_sqft": sqft or None, "commute_tolerance": commute,
                   "commute_destination": destination, "commute_mode": mode}
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
            st.write(pending["parsed"])
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
    st.caption(f"{number_label(item.get('bedrooms'), 'bed')} · {number_label(item.get('bathrooms'), 'bath')}")
    with st.form("property_fees"):
        fees = item.get("fees", {})
        st.caption("Monthly recurring fees apply only to this property.")
        fields = {}
        for key, label in [("parking", "Parking"), ("utilities", "Utilities"), ("pet_fee", "Pet fee"), ("renters_insurance", "Renters insurance"), ("other", "Other monthly fees")]:
            fields[key] = st.number_input(f"{label} ($/month)", min_value=0.0, value=float(fees.get(key) or 0), step=5.0)
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
        budget = st.number_input("Maximum monthly cost ($)", min_value=0, value=int(filters.get("max_budget") or 0))
        beds = st.number_input("Minimum bedrooms", min_value=0, value=int(filters.get("min_beds") or 0))
        sqft = st.number_input("Minimum square feet", min_value=0, value=int(filters.get("min_sqft") or 0))
        request = st.text_input("Natural-language request", value=filters.get("request", ""), disabled=not capability("can_use_natural_language_filtering"))
        priorities = {}
        if capability("can_use_lifestyle_score"):
            st.caption("Priority weights (0 ignores a priority; the backend normalizes the total).")
            for priority in ["budget", "commute", "safety", "nightlife", "gym"]:
                priorities[priority] = st.slider(priority.title(), 0.0, 5.0, float(filters.get("priorities", {}).get(priority, 1.0)), 0.5)
        apply = st.form_submit_button("Apply request and numeric filters")
    if apply:
        st.session_state["account_filters"] = {"max_budget": budget or None, "min_beds": beds, "min_sqft": sqft, "request": request, "priorities": priorities}
        filters = st.session_state["account_filters"]
    if st.button("Reset filters"):
        st.session_state["account_filters"] = {}
        st.rerun()
    if filters:
        st.caption(f"Applied filters: {filters}")
    constraints = {key: value for key, value in filters.items() if key in {"min_beds", "min_sqft"} and value}
    if filters.get("max_budget"):
        constraints["max_price"] = filters["max_budget"]
    if filters.get("request"):
        parsed_request = api_call(client, "POST", "/requests", {"request": filters["request"]})
        if parsed_request is None:
            return
        constraints = {**parsed_request.get("constraints", {}), **constraints}
        priorities = {**parsed_request.get("priorities", {}), **filters.get("priorities", {})}
    else:
        priorities = filters.get("priorities", {})
    if priorities and sum(priorities.values()) <= 0:
        st.warning("Choose at least one nonzero priority before applying.")
        return
    ids = [item["id"] for item in properties]
    if not ids:
        st.info("Save a listing to begin your comparison.")
        return
    result = api_call(client, "POST", "/ranking", {"property_ids": ids, "constraints": constraints, "priorities": priorities})
    if result is None:
        return
    rows = result.get("ranked", [])
    if not rows:
        st.info("No saved listings match these filters.")
        return
    st.caption(f"Applied constraints: {constraints or 'None'}")
    frame = pd.DataFrame(rows)
    for key, noun in [("beds_num", "bed"), ("bathrooms", "bath"), ("baths", "bath")]:
        if key in frame:
            frame[key] = frame[key].apply(lambda value: number_label(value, noun))
    display_frame(frame)
    if capability("can_export"):
        scope = st.selectbox("CSV export scope", ["properties", "units"], format_func=lambda value: "All property types" if value == "properties" else "Apartment units")
        if st.button("Prepare CSV export"):
            exported = api_call(client, "POST", "/exports", {"property_ids": ids, "format": "csv", "scope": scope}, raw=True)
            if exported is not None:
                st.session_state["account_export"] = exported
    if capability("can_export") and "account_export" in st.session_state:
        st.download_button("Download comparison CSV", st.session_state["account_export"], "nestai-comparison.csv", "text/csv")
    if capability("can_generate_ai_reports") and st.button("Generate decision report"):
        report = api_call(client, "POST", "/reports", {"property_ids": ids, "constraints": constraints, "priorities": priorities, "idempotency_key": str(uuid.uuid4())})
        if report is not None:
            st.session_state["account_report"] = report
    if capability("can_generate_ai_reports") and st.session_state.get("account_report"):
        report = st.session_state["account_report"]
        st.code(report["content"], language="json")
        if capability("can_export"):
            st.download_button("Download report", report["content"], report["filename"], report["media_type"])
    entitlements = st.session_state.get("account_entitlements", {})
    if entitlements.get("plan") == "premium_plus" and st.button("View advanced analytics"):
        analytics = api_call(client, "POST", "/analytics", {"property_ids": ids, "constraints": constraints, "priorities": priorities, "idempotency_key": str(uuid.uuid4())})
        if analytics is not None:
            st.write(analytics)


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
        from feedback import submit_feedback, send_feedback_email
        with st.form("account_feedback"):
            category = st.selectbox("Feedback category", ["bug", "feature_request", "improvement"])
            title = st.text_input("Feedback title")
            description = st.text_area("Describe the issue or suggestion")
            submitted = st.form_submit_button("Submit feedback")
        if submitted and title.strip():
            payload = {"category": category, "title": title, "description": description,
                       "user_plan": st.session_state["account_entitlements"].get("plan", "free"),
                       "platform": "web", "beta_tester": bool((auth.user() or {}).get("beta_access"))}
            try:
                reference = submit_feedback(payload)
                send_feedback_email(payload, reference)
                st.success(f"Feedback saved. Reference: {reference}")
            except Exception:
                st.error("Could not submit feedback. Please try again.")
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
