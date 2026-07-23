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

import streamlit as st

from feature_access import (
    capability,
    can_save_another_property,
    count_active_homes,
    require_capability,
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

# ── Session-state keys (homes tab only) ──────────────────────────────────────

_KEYS = {
    "home_text": "",
    "home_result": None,               # ParsedHomeResult | None
    "home_replace_pending": None,      # int | None (home_id to replace)
    "home_filter_min_price": 0,
    "home_filter_max_price": 0,
    "home_filter_min_beds": 0,
    "home_filter_min_baths": 0.0,
    "home_filter_min_sqft": 0,
    "home_sort_by": "Price (low → high)",
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

    # ── How-to expander ───────────────────────────────────────────────────────
    with st.expander("ℹ️ How to use the Homes tab", expanded=False):
        st.write("""
        **Load a Zillow listing and analyze it:**

        1. Open a Zillow listing (for rent or for sale).
        2. Scroll to the bottom of the listing page.
        3. Press **Ctrl + A** then **Ctrl + C** to copy all text.
        4. Paste into the box below and click **🔍 Analyze Home**.
        5. Review the parsed summary, facts, and features.
        6. Click **💾 Save Home** to add it to your saved list.
        7. Compare multiple saved homes in the **My Saved Homes** section below.

        Or try one of the example listings to see it in action.
        """)

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
            st.session_state.home_text = ""
            st.rerun()
    else:
        # Free plan: show replacement prompt
        st.warning(
            "⚠️ You've reached your saved-home limit on the **Free plan** (1 active home). "
            "Archive your existing saved home to make room, or upgrade to Premium."
        )
        oldest_id = get_oldest_active_home_id()
        c_replace, c_upgrade = st.columns(2)
        with c_replace:
            if oldest_id and st.button("♻️ Replace & Archive Old Home", use_container_width=True):
                archive_home(oldest_id)
                raw = st.session_state.get("home_text", "")
                home_id = save_home(result, raw_source_text=raw)
                st.success(f"✅ Old home archived. New home saved! (ID {home_id})")
                st.session_state.home_result = None
                st.session_state.home_text = ""
                st.rerun()
        with c_upgrade:
            st.button("⬆️ Upgrade to Premium", use_container_width=True, disabled=True)
            st.caption("_(Coming soon)_")


# ── Saved homes rendering ─────────────────────────────────────────────────────

def _render_saved_homes() -> None:
    active_homes = list_active_homes()
    archived_homes = list_archived_homes()

    if not active_homes and not archived_homes:
        st.info("No saved homes yet. Analyze and save a listing above.")
        return

    st.markdown("### My Saved Homes")

    # ── Filter controls ───────────────────────────────────────────────────────
    if active_homes:
        with st.expander("🔧 Filter & Sort", expanded=False):
            fc1, fc2, fc3 = st.columns(3)
            min_price = fc1.number_input("Min price ($/mo or $)", value=0, step=100, key="home_filter_min_price")
            max_price = fc1.number_input("Max price ($/mo or $)", value=0, step=100, key="home_filter_max_price")
            min_beds = fc2.number_input("Min bedrooms", value=0, step=1, key="home_filter_min_beds")
            min_baths = fc2.number_input("Min bathrooms", value=0.0, step=0.5, key="home_filter_min_baths")
            min_sqft = fc3.number_input("Min sq ft", value=0, step=50, key="home_filter_min_sqft")
            sort_options = [
                "Price (low → high)",
                "Price (high → low)",
                "Sq Ft (large → small)",
                "Walk Score (high → low)",
                "Most recently saved",
            ]
            sort_by = fc3.selectbox("Sort by", sort_options, key="home_sort_by")

        filtered = _apply_filters(active_homes)
        filtered = _apply_sort(filtered)

        if not filtered:
            st.warning("No homes match the current filters.")
        else:
            _render_home_cards(filtered)

        # ── Comparison view (Premium) ─────────────────────────────────────────
        if capability("can_compare_multiple_properties") and len(filtered) >= 2:
            _render_comparison_table(filtered)
        elif len(active_homes) >= 2:
            st.info("💡 Upgrade to Premium to compare multiple homes side-by-side.")

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


def _render_home_cards(homes: list[dict]) -> None:
    for home in homes:
        with st.container():
            title = home.get("display_name") or home.get("address") or "Saved Home"
            ptype = home.get("property_type") or ""
            badges = {
                "RENTAL_HOME": "🔑 Rental",
                "HOME_FOR_SALE": "🏷️ For Sale",
            }
            type_str = badges.get(ptype, ptype)

            price_str = (
                f"${home.get('monthly_rent', 0):,}/mo"
                if home.get("monthly_rent")
                else (f"${home.get('sale_price', 0):,}" if home.get("sale_price") else "—")
            )

            st.markdown(f"**{title}** — {type_str}")

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Price", price_str)
            m2.metric("Beds", home.get("bedrooms") or "—")
            m3.metric("Baths", home.get("bathrooms") or "—")
            m4.metric("Sq Ft", f"{home.get('square_feet'):,}" if home.get("square_feet") else "—")
            ws = home.get("walk_score")
            m5.metric("Walk Score", f"{ws}/100" if ws is not None else "—")

            # Features preview
            features_raw = home.get("features_json") or "[]"
            try:
                features = json.loads(features_raw) if isinstance(features_raw, str) else features_raw
            except (json.JSONDecodeError, TypeError):
                features = []
            if features:
                st.caption("✨ " + " · ".join(features[:4]) + ("…" if len(features) > 4 else ""))

            # Archive button
            if st.button("🗄️ Archive", key=f"archive_{home['id']}", help="Archive this home"):
                archive_home(home["id"])
                st.rerun()

            st.divider()


def _render_comparison_table(homes: list[dict]) -> None:
    st.markdown("#### 📊 Side-by-Side Comparison")

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
    st.dataframe(df, use_container_width=True)
