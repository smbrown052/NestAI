"""
homes_tab.py
Streamlit UI for the Homes tab — Zillow rental/for-sale home workflow.

This module is called from app.py inside a ``with homes_tab:`` block.
It has no side effects on the Apartments tab state.

NOTE:
    All save/quota enforcement is LOCAL (session-based).
    See feature_access.py and home_storage.py for details.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from feature_access import (
    capability,
    can_save_another_property,
    get_plan,
)
from home_storage import (
    archive_home,
    count_active_homes as _count_active,
    get_oldest_active_home_id,
    list_active_homes,
    list_archived_homes,
    restore_home,
    save_home,
)
from parser.home_listing import (
    ParsedHomeResult,
    get_fixture_path,
    parse_home_listing_text,
)
from plan_ui import render_upgrade_prompt, navigate_to_plans
from ui_theme import normalize_plan, tier_class

# ── Session-state keys (homes tab only) ──────────────────────────────────────

_KEYS = {
    "home_text": "",
    "home_text_should_clear": False,   # deferred clear flag — set True to wipe the text_area on next rerun
    "home_result": None,               # ParsedHomeResult | None
    "home_replace_pending": None,      # int | None (home_id to replace)
    "home_filter_min_price": 0,
    "home_filter_max_price": 0,
    "home_filter_min_beds": 0,
    "home_filter_min_baths": 0.0,
    "home_filter_min_sqft": 0,
    "home_sort_by": "Price (low → high)",
    "home_ai_pref_text": "",          # free-text AI preferences for homes
}

def _init_state() -> None:
    for k, v in _KEYS.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── Fixture labels ─────────────────────────────────────────────────────────────

_FIXTURE_1_LABEL = "🏠 3624 Valley Dr, Alexandria VA"
_FIXTURE_2_LABEL = "🏠 3507 Martha Custis Dr, Alexandria VA"


# ── Helper: format price ──────────────────────────────────────────────────────

def _fmt_price(result: ParsedHomeResult) -> str:
    if result.monthly_rent:
        return f"${result.monthly_rent:,}/mo"
    if result.sale_price:
        return f"${result.sale_price:,}"
    return result.price_raw or "—"


# ── Helper: property type badge ───────────────────────────────────────────────

def _type_badge(result: ParsedHomeResult) -> str:
    badges = {
        "RENTAL_HOME": "🔑 Rental",
        "HOME_FOR_SALE": "🏷️ For Sale",
        "APARTMENT_UNIT": "🏢 Apt",
        "CONDO": "🏙️ Condo",
        "TOWNHOME": "🏘️ Townhome",
    }
    return badges.get(result.property_type or "", result.property_type or "Home")


# ── Homes workflow ─────────────────────────────────────────────────────────────

def render_homes_tab() -> None:
    _init_state()

    # ── Page header with Zillow link + instruction ────────────────────────────
    st.markdown(
        "🏠 Source: <a href='https://www.zillow.com' target='_blank'>Zillow</a>",
        unsafe_allow_html=True,
    )
    st.info(
        "Expand all units before pressing Ctrl+A. "
        "Listings are not synced, so refresh the source page and paste again to update results."
    )

    # ── Example buttons + paste area ─────────────────────────────────────────
    st.markdown("### 1. Paste Zillow Listing Text")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button(_FIXTURE_1_LABEL, use_container_width=True):
            try:
                st.session_state.home_text = get_fixture_path("home_example_1.txt").read_text(encoding="utf-8")
                st.session_state.home_result = None
            except FileNotFoundError:
                st.error("Example 1 fixture not found.")
            st.rerun()

    with col2:
        if st.button(_FIXTURE_2_LABEL, use_container_width=True):
            try:
                st.session_state.home_text = get_fixture_path("home_example_2.txt").read_text(encoding="utf-8")
                st.session_state.home_result = None
            except FileNotFoundError:
                st.error("Example 2 fixture not found.")
            st.rerun()

    with col3:
        if st.button("🧹 Clear", use_container_width=True):
            st.session_state.home_text = ""
            st.session_state.home_result = None
            st.rerun()

    # Apply deferred clear of the text_area value BEFORE the widget is instantiated.
    # This avoids the StreamlitAPIException raised when widget-backed keys are mutated
    # after their widget has already been rendered in the same script run.
    if st.session_state.get("home_text_should_clear"):
        st.session_state["home_text"] = ""
        st.session_state.home_text_should_clear = False

    home_text = st.text_area(
        "Zillow listing text",
        key="home_text",
        height=280,
        placeholder="Paste copied Zillow listing text here…",
    )

    analyze_clicked = st.button("🔍 Analyze Home", use_container_width=True)

    if analyze_clicked:
        text = st.session_state.home_text.strip()
        if not text:
            st.warning("Paste Zillow listing text first, or load an example.")
        else:
            with st.spinner("Parsing…"):
                result = parse_home_listing_text(text)
            st.session_state.home_result = result

    # ── Parsed result ─────────────────────────────────────────────────────────
    result: ParsedHomeResult | None = st.session_state.home_result

    if result is not None:
        _render_home_result(result)

    # ── Saved homes ───────────────────────────────────────────────────────────
    st.divider()
    _render_saved_homes()


# ── Parsed result rendering ───────────────────────────────────────────────────

def _render_home_result(result: ParsedHomeResult) -> None:
    st.markdown("### 2. Home Summary")

    # ── Warnings ──────────────────────────────────────────────────────────────
    if result.warnings:
        with st.expander(f"⚠️ {len(result.warnings)} parse warning(s)", expanded=False):
            for w in result.warnings:
                st.caption(f"• {w}")

    # ── Top metric tiles ──────────────────────────────────────────────────────
    type_label = _type_badge(result)
    price_label = _fmt_price(result)

    t1, t2, t3, t4, t5 = st.columns(5)
    t1.metric("Type", type_label)
    t2.metric("Price", price_label)
    t3.metric("Beds", str(result.bedrooms) if result.bedrooms is not None else "—")
    t4.metric(
        "Baths",
        str(result.bathrooms) if result.bathrooms is not None else "—",
    )
    t5.metric(
        "Sq Ft",
        f"{result.square_feet:,}" if result.square_feet is not None else "—",
    )

    # ── Address ───────────────────────────────────────────────────────────────
    if result.address:
        st.caption(f"📍 {result.address}")

    # ── Secondary metrics ─────────────────────────────────────────────────────
    sec_cols = st.columns(4)
    if result.available_date:
        sec_cols[0].caption(f"📅 Available: {result.available_date}")
    if result.pets_policy:
        sec_cols[1].caption(f"🐾 Pets: {result.pets_policy}")
    if result.walk_score is not None:
        sec_cols[2].caption(f"🚶 Walk {result.walk_score} · 🚌 Transit {result.transit_score or '—'} · 🚲 Bike {result.bike_score or '—'}")
    zillow_time = (
        f"{result.hours_on_zillow}h" if result.hours_on_zillow is not None
        else (f"{result.days_on_zillow}d" if result.days_on_zillow is not None else None)
    )
    if zillow_time:
        sec_cols[3].caption(f"⏱ {zillow_time} on Zillow")

    # ── Home facts ────────────────────────────────────────────────────────────
    facts = {}
    if result.property_subtype:
        facts["Subtype"] = result.property_subtype
    if result.cooling:
        facts["Cooling"] = result.cooling
    if result.heating:
        facts["Heating"] = result.heating
    if result.parking:
        facts["Parking"] = result.parking
    if result.laundry:
        facts["Laundry"] = result.laundry

    if facts:
        with st.expander("🔍 Home Facts", expanded=True):
            fcols = st.columns(min(len(facts), 3))
            for i, (k, v) in enumerate(facts.items()):
                fcols[i % len(fcols)].markdown(f"**{k}:** {v}")

    # ── Features ──────────────────────────────────────────────────────────────
    if result.features:
        with st.expander(f"✨ Features ({len(result.features)})", expanded=False):
            for feat in result.features:
                st.markdown(f"• {feat}")

    # ── Schools ───────────────────────────────────────────────────────────────
    if result.schools:
        with st.expander(f"🏫 Schools ({len(result.schools)})", expanded=False):
            for school in result.schools:
                st.caption(school)

    # ── Description ───────────────────────────────────────────────────────────
    if result.description:
        with st.expander("📝 Description", expanded=False):
            st.write(result.description)

    # ── Save button ───────────────────────────────────────────────────────────
    st.markdown("### 3. Save This Home")
    _render_save_button(result)


def _render_save_button(result: ParsedHomeResult) -> None:
    active_count = _count_active()
    can_save = can_save_another_property(active_count)

    if can_save:
        if st.button("💾 Save Home", use_container_width=True):
            raw = st.session_state.get("home_text", "")
            home_id = save_home(result, raw_source_text=raw)
            st.success(f"✅ Home saved! (ID {home_id})")
            st.session_state.home_result = None
            st.session_state.home_text_should_clear = True
            st.rerun()
    else:
        render_upgrade_prompt("can_save_property", "Save Additional Home")
        oldest_id = get_oldest_active_home_id()
        c_replace, c_upgrade = st.columns(2)
        with c_replace:
            if oldest_id and st.button("♻️ Replace & Archive Old Home", use_container_width=True):
                archive_home(oldest_id)
                raw = st.session_state.get("home_text", "")
                home_id = save_home(result, raw_source_text=raw)
                st.success(f"✅ Old home archived. New home saved! (ID {home_id})")
                st.session_state.home_result = None
                st.session_state.home_text_should_clear = True
                st.rerun()
        with c_upgrade:
            if st.button("⬆️ Upgrade to Premium", use_container_width=True, key="homes_upgrade_btn"):
                navigate_to_plans(highlight_plan="PREMIUM")


# ── Saved homes rendering ─────────────────────────────────────────────────────

def _render_saved_homes() -> None:
    active_homes = list_active_homes()
    archived_homes = list_archived_homes()

    if not active_homes and not archived_homes:
        st.info("No saved homes yet. Analyze and save a listing above.")
        return

    # ── Compact header with Clear All ─────────────────────────────────────────
    hdr_col, clear_col = st.columns([4, 1])
    with hdr_col:
        st.markdown(f"### My Saved Homes &nbsp; <span style='font-size:0.85rem;color:#888;'>{len(active_homes)} saved</span>", unsafe_allow_html=True)
    with clear_col:
        if active_homes and st.button("Clear All", use_container_width=True, type="secondary", key="homes_clear_all"):
            for home in active_homes:
                archive_home(home["id"])
            st.rerun()

    if active_homes:
        # ── Analysis: AI prefs + priorities + ranked breakdown + brief ────────
        _render_home_analysis(active_homes)

        # ── Comparison table at the bottom ────────────────────────────────────
        if len(active_homes) >= 2:
            if len(active_homes) <= 2 or capability("can_compare_multiple_properties"):
                _render_comparison_table(active_homes)
            else:
                render_upgrade_prompt(
                    "can_compare_multiple_properties",
                    "Compare More Than 2 Homes",
                )

    # ── Archived homes ────────────────────────────────────────────────────────
    if archived_homes:
        with st.expander(f"🗄️ Archived Homes ({len(archived_homes)})", expanded=False):
            for home in archived_homes:
                c_info, c_restore = st.columns([4, 1])
                with c_info:
                    price_str = (
                        f"${home.get('monthly_rent', 0):,}/mo"
                        if home.get("monthly_rent")
                        else (f"${home.get('sale_price', 0):,}" if home.get("sale_price") else "—")
                    )
                    st.caption(
                        f"**{home.get('display_name') or home.get('address') or 'Unknown'}** — "
                        f"{price_str}, {home.get('bedrooms') or '?'} bed, "
                        f"{home.get('bathrooms') or '?'} bath"
                    )
                with c_restore:
                    can_restore = capability("can_restore_archived_property")
                    if can_restore:
                        if st.button("Restore", key=f"restore_{home['id']}"):
                            restore_home(home["id"])
                            st.rerun()
                    else:
                        st.caption("_Upgrade to restore_")


# ── Home priorities + AI preference + ranked analysis ─────────────────────────

def _render_home_priorities() -> dict:
    """Render structured home priority controls and return the prefs dict."""
    st.markdown("#### 🎯 Home Priorities")
    st.caption("Set your preferences. Yes/No affect scoring; No preference is neutral.")

    col1, col2, col3 = st.columns(3)
    with col1:
        rent_buy = st.selectbox(
            "🏷️ Rent / Buy",
            ["Rent", "Buy", "No preference"],
            key="home_pref_rent_buy",
            index=2,
        )
        min_beds = st.selectbox(
            "🛏 Min bedrooms",
            ["Any", "1", "2", "3", "4+"],
            key="home_pref_min_beds",
            index=0,
        )
        min_baths = st.selectbox(
            "🛁 Min bathrooms",
            ["Any", "1", "1.5", "2", "2.5", "3+"],
            key="home_pref_min_baths",
            index=0,
        )
        garage = st.selectbox(
            "🚗 Garage spaces",
            ["Any", "1+", "2+"],
            key="home_pref_garage",
            index=0,
        )
    with col2:
        min_sqft_opt = st.selectbox(
            "📐 Min sq ft",
            ["Any", "500", "1000", "1500", "2000", "2500", "3000+"],
            key="home_pref_min_sqft",
            index=0,
        )
        hoa = st.selectbox(
            "🏘 HOA",
            ["Yes", "No", "No preference"],
            key="home_pref_hoa",
            index=2,
        )
        basement = st.selectbox(
            "🏠 Basement",
            ["Yes", "No", "No preference"],
            key="home_pref_basement",
            index=2,
        )
        outdoor = st.selectbox(
            "🌿 Outdoor space",
            ["Yes", "No", "No preference"],
            key="home_pref_outdoor",
            index=2,
        )
    with col3:
        property_type_pref = st.selectbox(
            "🏡 Property type",
            ["Any", "House", "Condo", "Townhome", "Multi-family"],
            key="home_pref_property_type",
            index=0,
        )
        year_built = st.selectbox(
            "📅 Year built",
            ["Any", "2010+", "2000+", "1990+", "1980+"],
            key="home_pref_year_built",
            index=0,
        )
        min_lot = st.selectbox(
            "🌱 Min lot size",
            ["Any", "0.1 acre", "0.25 acre", "0.5 acre", "1 acre+"],
            key="home_pref_min_lot",
            index=0,
        )
        pets = st.selectbox(
            "🐾 Pets",
            ["Yes", "No", "No preference"],
            key="home_pref_pets",
            index=2,
        )

    return {
        "rent_buy": rent_buy,
        "min_beds": min_beds,
        "min_baths": min_baths,
        "garage": garage,
        "min_sqft": min_sqft_opt,
        "hoa": hoa,
        "basement": basement,
        "outdoor": outdoor,
        "property_type": property_type_pref,
        "year_built": year_built,
        "min_lot": min_lot,
        "pets": pets,
    }


def _score_home(home: dict, prefs: dict, all_homes: list[dict]) -> float:
    """Return a 0–100 NestAI score for a home based on user preferences."""
    score = 50.0  # neutral baseline

    # ── Price score (lower is better, normalized against peers) ──────────────
    all_prices = [
        h.get("monthly_rent") or h.get("sale_price") or 0
        for h in all_homes
        if h.get("monthly_rent") or h.get("sale_price")
    ]
    price = home.get("monthly_rent") or home.get("sale_price") or 0
    if price > 0 and len(all_prices) > 1:
        max_p, min_p = max(all_prices), min(all_prices)
        if max_p > min_p:
            score += ((max_p - price) / (max_p - min_p) - 0.5) * 30

    # ── Space score ───────────────────────────────────────────────────────────
    all_sqft = [h.get("square_feet") or 0 for h in all_homes if h.get("square_feet")]
    sqft = home.get("square_feet") or 0
    if sqft > 0 and len(all_sqft) > 1:
        max_s, min_s = max(all_sqft), min(all_sqft)
        if max_s > min_s:
            score += ((sqft - min_s) / (max_s - min_s) - 0.5) * 15

    # ── Walk score ────────────────────────────────────────────────────────────
    ws = home.get("walk_score")
    if ws is not None:
        score += (int(ws) / 100 - 0.5) * 10

    def _pref_adjust(has_feature: bool | None, pref: str, weight: float = 6.0) -> float:
        if pref == "Yes":
            return weight if has_feature else -weight
        if pref == "No":
            return weight if not has_feature else -weight
        return 0.0

    # ── Rent/Buy preference ───────────────────────────────────────────────────
    rent_buy = prefs.get("rent_buy", "No preference")
    ptype = home.get("property_type") or ""
    if rent_buy == "Rent" and ptype != "RENTAL_HOME":
        score -= 20
    elif rent_buy == "Buy" and ptype != "HOME_FOR_SALE":
        score -= 20

    # ── Min bedrooms filter ───────────────────────────────────────────────────
    min_beds_map = {"1": 1, "2": 2, "3": 3, "4+": 4}
    mb = min_beds_map.get(prefs.get("min_beds", "Any"))
    if mb is not None:
        beds = home.get("bedrooms") or 0
        if beds < mb:
            score -= (mb - beds) * 10

    # ── Min bathrooms filter ──────────────────────────────────────────────────
    min_baths_map = {"1": 1.0, "1.5": 1.5, "2": 2.0, "2.5": 2.5, "3+": 3.0}
    mbath = min_baths_map.get(prefs.get("min_baths", "Any"))
    if mbath is not None:
        baths = home.get("bathrooms") or 0.0
        if baths < mbath:
            score -= (mbath - baths) * 8

    # ── Min sqft ──────────────────────────────────────────────────────────────
    min_sqft_map = {"500": 500, "1000": 1000, "1500": 1500, "2000": 2000, "2500": 2500, "3000+": 3000}
    msqft = min_sqft_map.get(prefs.get("min_sqft", "Any"))
    if msqft is not None and sqft > 0 and sqft < msqft:
        score -= min(15, (msqft - sqft) / msqft * 15)

    # ── Pets ──────────────────────────────────────────────────────────────────
    pets_text = str(home.get("pets_policy") or "").lower()
    has_pets = any(k in pets_text for k in ("yes", "allowed", "ok", "welcome", "friendly"))
    score += _pref_adjust(has_pets, prefs.get("pets", "No preference"))

    # ── Feature preferences (inferred from features_json / description) ───────
    features_raw = home.get("features_json") or "[]"
    try:
        features_list = json.loads(features_raw) if isinstance(features_raw, str) else features_raw
        features_text = " ".join(f.lower() for f in features_list)
    except (json.JSONDecodeError, TypeError):
        features_text = ""
    desc = str(home.get("description") or "").lower()
    all_text = features_text + " " + desc

    has_basement = "basement" in all_text or "lower level" in all_text
    score += _pref_adjust(has_basement, prefs.get("basement", "No preference"))

    has_outdoor = any(k in all_text for k in ("yard", "patio", "deck", "garden", "outdoor"))
    score += _pref_adjust(has_outdoor, prefs.get("outdoor", "No preference"))

    # ── HOA (mark unknown if not in text; don't penalize unknown) ────────────
    hoa_pref = prefs.get("hoa", "No preference")
    if hoa_pref != "No preference":
        hoa_mentioned = "hoa" in all_text or "homeowner" in all_text or "association fee" in all_text
        if hoa_mentioned:
            has_hoa = not ("no hoa" in all_text or "hoa: none" in all_text)
            score += _pref_adjust(has_hoa, hoa_pref)
        # If HOA is unknown, don't penalize either way

    # ── Garage ────────────────────────────────────────────────────────────────
    garage_pref = prefs.get("garage", "Any")
    if garage_pref != "Any":
        parking_text = str(home.get("parking") or "").lower()
        has_garage = "garage" in parking_text or "garage" in all_text
        garage_spaces_text = parking_text + all_text
        has_2_garage = has_garage and ("2-car" in garage_spaces_text or "2 car" in garage_spaces_text or "two-car" in garage_spaces_text)
        if garage_pref == "1+":
            score += 6 if has_garage else -6
        elif garage_pref == "2+":
            score += 6 if has_2_garage else (-6 if not has_garage else -3)

    return max(0.0, min(100.0, round(score, 1)))


def _explain_home_rank(home: dict, rank: int, all_homes: list[dict], prefs: dict) -> str:
    """Generate a short explanation for why a home ranked at this position."""
    lines = []

    price = home.get("monthly_rent") or home.get("sale_price") or 0
    all_prices = [h.get("monthly_rent") or h.get("sale_price") or 0 for h in all_homes if h.get("monthly_rent") or h.get("sale_price")]
    if price > 0 and all_prices:
        avg_price = sum(all_prices) / len(all_prices)
        if price < avg_price * 0.95:
            lines.append(f"💰 ${price:,} — below the group average (${avg_price:,.0f})")
        elif price > avg_price * 1.05:
            lines.append(f"💰 ${price:,} — above the group average (${avg_price:,.0f})")
        else:
            lines.append(f"💰 ${price:,} — near the group average")

    sqft = home.get("square_feet")
    if sqft:
        all_sqft = [h.get("square_feet") for h in all_homes if h.get("square_feet")]
        if all_sqft:
            avg_sqft = sum(all_sqft) / len(all_sqft)
            if sqft >= avg_sqft * 1.05:
                lines.append(f"📐 {sqft:,} sq ft — above average space")
            elif sqft < avg_sqft * 0.95:
                lines.append(f"📐 {sqft:,} sq ft — below average space")

    beds = home.get("bedrooms")
    baths = home.get("bathrooms")
    if beds is not None:
        lines.append(f"🛏 {beds} bed / {baths or '?'} bath")

    ws = home.get("walk_score")
    if ws is not None:
        lines.append(f"🚶 Walk score: {ws}/100")

    return "\n".join(f"• {l}" for l in lines) if lines else f"• Rank #{rank} based on price, space, and neighborhood data."


def _render_home_analysis(homes: list[dict]) -> None:
    """Render AI preference input, home priorities, ranked breakdown, and decision brief."""
    if len(homes) < 1:
        return

    st.divider()
    st.markdown("#### 💬 AI Preferences (optional)")
    st.caption("Describe what matters most in plain language. This is used alongside the priorities below.")
    ai_pref_text = st.text_input(
        "AI preference text",
        key="home_ai_pref_text",
        placeholder="e.g. Need a quiet neighborhood, prefer newer construction, must have a yard",
        label_visibility="collapsed",
    )

    prefs = _render_home_priorities()

    if len(homes) < 2:
        st.info("Save at least 2 homes to see rankings and tradeoff analysis.")
        return

    # ── Compute scores ────────────────────────────────────────────────────────
    scored = []
    for home in homes:
        s = _score_home(home, prefs, homes)
        scored.append({**home, "nestai_home_score": s})

    scored.sort(key=lambda h: h["nestai_home_score"], reverse=True)

    # ── Ranked breakdown ──────────────────────────────────────────────────────
    visual_tier = normalize_plan(get_plan())

    st.divider()
    st.markdown("#### 🏆 Ranked Breakdown")
    st.caption("Ranked by your priorities. Tradeoffs explain why each choice was selected over the next.")

    for rank, home in enumerate(scored, start=1):
        title = home.get("display_name") or home.get("address") or f"Home {rank}"
        price_str = (
            f"${home.get('monthly_rent', 0):,}/mo"
            if home.get("monthly_rent")
            else (f"${home.get('sale_price', 0):,}" if home.get("sale_price") else "—")
        )
        score = home["nestai_home_score"]

        with st.expander(
            f"Rank #{rank} · {title} · Score {score:.0f}/100",
            expanded=(rank == 1),
        ):
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("NestAI Score", f"{score:.0f}/100")
            m2.metric("Price", price_str)
            m3.metric("Beds", home.get("bedrooms") or "—")
            m4.metric("Baths", home.get("bathrooms") or "—")
            m5.metric("Sq Ft", f"{home.get('square_feet'):,}" if home.get("square_feet") else "—")

            tab_why, tab_tradeoffs = st.tabs(["📊 Why This Rank", "💡 Tradeoffs"])

            with tab_why:
                st.markdown(_explain_home_rank(home, rank, homes, prefs))

            with tab_tradeoffs:
                if rank == 1 and len(scored) > 1:
                    runner = scored[1]
                    _render_home_tradeoff(home, runner, why_winner=True)
                elif rank > 1:
                    above = scored[rank - 2]
                    _render_home_tradeoff(above, home, why_winner=False)
                else:
                    st.info("Add another home to see tradeoff analysis.")

    # ── Executive Decision Brief ──────────────────────────────────────────────
    if len(scored) >= 2:
        st.divider()
        _render_home_decision_brief(scored, visual_tier)


def _render_home_tradeoff(home_a: dict, home_b: dict, *, why_winner: bool) -> None:
    """
    Show a tradeoff comparison between two homes.

    If why_winner=True: explain why home_a (rank#1) beat home_b (rank#2).
    If why_winner=False: show what home_b has that home_a doesn't.
    """
    label_a = home_a.get("display_name") or home_a.get("address") or "Home A"
    label_b = home_b.get("display_name") or home_b.get("address") or "Home B"

    price_a = home_a.get("monthly_rent") or home_a.get("sale_price") or 0
    price_b = home_b.get("monthly_rent") or home_b.get("sale_price") or 0
    sqft_a = home_a.get("square_feet") or 0
    sqft_b = home_b.get("square_feet") or 0
    ws_a = home_a.get("walk_score") or 0
    ws_b = home_b.get("walk_score") or 0
    beds_a = home_a.get("bedrooms") or 0
    beds_b = home_b.get("bedrooms") or 0

    if why_winner:
        st.markdown(f"**Why {label_a} (Rank #1) beat {label_b} (Rank #2):**")
        advantages = []
        if price_a > 0 and price_b > 0 and price_a < price_b:
            advantages.append(f"💰 ${price_b - price_a:,} less expensive")
        if sqft_a > sqft_b + 50:
            advantages.append(f"📐 {sqft_a - sqft_b:,} sq ft more space")
        if ws_a > ws_b + 5:
            advantages.append(f"🚶 Walk score {ws_a} vs {ws_b}")
        if beds_a > beds_b:
            advantages.append(f"🛏 {beds_a} bed vs {beds_b} bed")
        score_a = home_a.get("nestai_home_score", 0)
        score_b = home_b.get("nestai_home_score", 0)
        if score_a > score_b:
            advantages.append(f"🏆 {score_a - score_b:.0f} pt NestAI Score advantage")
        for adv in (advantages or ["Higher overall score from your priorities"]):
            st.markdown(f"• {adv}")
        # Key compromise
        if price_a > 0 and price_b > 0 and price_a > price_b:
            st.markdown(f"\n**Key compromise:** Costs ${price_a - price_b:,} more than runner-up.")
    else:
        st.markdown(f"**Comparing {label_a} (higher rank) vs {label_b} (this home):**")
        price_diff = price_b - price_a
        if price_diff > 0:
            st.markdown(f"• 💰 Choosing this home costs ${price_diff:,} more/month")
        elif price_diff < 0:
            st.markdown(f"• 💰 This home costs ${abs(price_diff):,} less/month")
        else:
            st.markdown("• 💰 Same price")
        if sqft_b > sqft_a + 50:
            st.markdown(f"• 📐 Gains {sqft_b - sqft_a:,} sq ft more space")
        elif sqft_b < sqft_a - 50:
            st.markdown(f"• 📐 Loses {sqft_a - sqft_b:,} sq ft compared to rank above")
        if ws_b > ws_a + 5:
            st.markdown(f"• 🚶 Better walkability: {ws_b} vs {ws_a}")
        if beds_b > beds_a:
            st.markdown(f"• 🛏 More bedrooms: {beds_b} vs {beds_a}")


def _render_home_decision_brief(scored: list[dict], visual_tier: str) -> None:
    """Render Executive Decision Brief for homes."""
    from ui_theme import metric_card_html

    winner = scored[0]
    runner_up = scored[1]

    winner_label = winner.get("display_name") or winner.get("address") or "Top Home"
    runner_label = runner_up.get("display_name") or runner_up.get("address") or "Runner-up"

    price_w = winner.get("monthly_rent") or winner.get("sale_price") or 0
    price_r = runner_up.get("monthly_rent") or runner_up.get("sale_price") or 0
    sqft_w = winner.get("square_feet") or 0
    sqft_r = runner_up.get("square_feet") or 0

    # Why winner won
    why_parts = []
    if price_w > 0 and price_r > 0:
        if price_w < price_r:
            why_parts.append(f"${price_r - price_w:,} less expensive")
        elif price_w > price_r:
            why_parts.append(f"${price_w - price_r:,} more expensive but higher scored")
    if sqft_w > sqft_r + 50:
        why_parts.append(f"{sqft_w - sqft_r:,} sq ft more space")
    score_margin = winner.get("nestai_home_score", 0) - runner_up.get("nestai_home_score", 0)
    if score_margin > 0:
        why_parts.append(f"{score_margin:.0f} pt score advantage")
    why_wins = " · ".join(why_parts) if why_parts else "Higher overall match to your priorities"

    # Key compromise
    compromise_parts = []
    if price_w > 0 and price_r > 0 and price_w > price_r:
        compromise_parts.append(f"${price_w - price_r:,} more expensive")
    if sqft_w > 0 and sqft_r > 0 and sqft_w < sqft_r:
        compromise_parts.append(f"{sqft_r - sqft_w:,} sq ft less space than runner-up")
    main_compromise = "; ".join(compromise_parts) if compromise_parts else "Minor tradeoffs only"

    cards = [
        ("Best Choice", winner_label),
        ("Why It Wins", why_wins),
        ("Key Compromise", main_compromise),
        ("Best Alternative", runner_label),
    ]

    st.markdown("### Executive Decision Brief")
    st.caption("Explains why the top home won, what it gives up, and the strongest alternative.")
    cols = st.columns(len(cards))
    for col, (label, value) in zip(cols, cards):
        with col:
            st.markdown(metric_card_html(label, value, tier=visual_tier), unsafe_allow_html=True)


def _apply_filters(homes: list[dict]) -> list[dict]:
    min_price = st.session_state.home_filter_min_price or 0
    max_price = st.session_state.home_filter_max_price or 0
    min_beds = st.session_state.home_filter_min_beds or 0
    min_baths = st.session_state.home_filter_min_baths or 0.0
    min_sqft = st.session_state.home_filter_min_sqft or 0

    out = []
    for h in homes:
        price = h.get("monthly_rent") or h.get("sale_price") or 0
        if min_price and price < min_price:
            continue
        if max_price and price > max_price:
            continue
        beds = h.get("bedrooms") or 0
        if min_beds and beds < min_beds:
            continue
        baths = h.get("bathrooms") or 0.0
        if min_baths and baths < min_baths:
            continue
        sqft = h.get("square_feet") or 0
        if min_sqft and sqft < min_sqft:
            continue
        out.append(h)
    return out


def _apply_sort(homes: list[dict]) -> list[dict]:
    sort_by = st.session_state.home_sort_by or "Price (low → high)"

    def price_key(h):
        return h.get("monthly_rent") or h.get("sale_price") or 0

    if sort_by == "Price (low → high)":
        return sorted(homes, key=price_key)
    if sort_by == "Price (high → low)":
        return sorted(homes, key=price_key, reverse=True)
    if sort_by == "Sq Ft (large → small)":
        return sorted(homes, key=lambda h: h.get("square_feet") or 0, reverse=True)
    if sort_by == "Walk Score (high → low)":
        return sorted(homes, key=lambda h: h.get("walk_score") or 0, reverse=True)
    # Most recently saved (default)
    return sorted(homes, key=lambda h: h.get("created_at") or "", reverse=True)


def _render_comparison_table(homes: list[dict]) -> None:
    visual_tier = normalize_plan(get_plan())
    st.markdown(
        (
            f"<div class='nestai-comparison-card {tier_class(visual_tier)}'>"
            "<div class='nestai-eyebrow'>Premium comparison</div>"
            "<h3>Side-by-side comparison</h3>"
            "<p class='nestai-section-note'>Compare saved homes in one clean panel instead of flipping between cards.</p>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    def price_str(h):
        if h.get("monthly_rent"):
            return f"${h['monthly_rent']:,}/mo"
        if h.get("sale_price"):
            return f"${h['sale_price']:,}"
        return "—"

    rows = {
        "Address": [h.get("display_name") or h.get("address") or "—" for h in homes],
        "Price": [price_str(h) for h in homes],
        "Beds": [h.get("bedrooms") or "—" for h in homes],
        "Baths": [h.get("bathrooms") or "—" for h in homes],
        "Sq Ft": [f"{h.get('square_feet'):,}" if h.get("square_feet") else "—" for h in homes],
        "Walk Score": [h.get("walk_score") or "—" for h in homes],
        "Transit Score": [h.get("transit_score") or "—" for h in homes],
        "Bike Score": [h.get("bike_score") or "—" for h in homes],
        "Available": [h.get("available_date") or "—" for h in homes],
        "Pets": [h.get("pets_policy") or "—" for h in homes],
        "Cooling": [h.get("cooling") or "—" for h in homes],
        "Heating": [h.get("heating") or "—" for h in homes],
        "Parking": [h.get("parking") or "—" for h in homes],
        "Laundry": [h.get("laundry") or "—" for h in homes],
    }

    import pandas as pd

    df = pd.DataFrame(rows).set_index("Address").T

    # Streamlit/PyArrow requires each displayed column to use consistent types.
    display_df = df.fillna("—").astype(str)

    st.dataframe(display_df, width="stretch")
