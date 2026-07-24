"""
pages/2_Admin.py — NestAI administrator portal.

Access is restricted to users with is_admin=True.
Redirects to the Account page (login) if unauthenticated.
Returns an "Access Denied" view if authenticated but not an admin.
"""

import streamlit as st
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from auth_client import (
    get_me,
    admin_get_overview,
    admin_get_users,
    admin_get_feedback,
    admin_user_action,
    admin_invite_beta,
    admin_get_beta_users,
    admin_get_beta_invitations,
    admin_update_feedback,
    admin_get_billing,
    admin_get_analytics,
    admin_get_audit_log,
    admin_get_ai_costs,
)

st.set_page_config(page_title="NestAI — Admin", page_icon="⚙️", layout="wide")

# ── Session state defaults ────────────────────────────────────────────────────

for key, default in {
    "auth_token": None,
    "auth_user": None,
    "admin_section": "dashboard",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ── Auth guard ────────────────────────────────────────────────────────────────

if not st.session_state.auth_token:
    st.title("⚙️ Admin Portal")
    st.warning("Please sign in to access the admin portal.")
    st.page_link("pages/1_Account.py", label="→ Sign In")
    st.stop()

# Verify token is still valid and user is admin
user_data, err = get_me(st.session_state.auth_token)
if err or not user_data:
    st.session_state.auth_token = None
    st.session_state.auth_user = None
    st.warning("Your session has expired. Please sign in again.")
    st.page_link("pages/1_Account.py", label="→ Sign In")
    st.stop()

st.session_state.auth_user = user_data

if not user_data.get("is_admin"):
    st.title("⚙️ Admin Portal")
    st.error("🚫 Access Denied — Administrator access required.")
    st.info("If you believe this is an error, contact your system administrator.")
    st.stop()

# ── Navigation ────────────────────────────────────────────────────────────────

token = st.session_state.auth_token

with st.sidebar:
    st.markdown("## ⚙️ Admin Portal")
    st.caption(f"Logged in as **{user_data.get('email', '')}**")
    st.divider()

    sections = {
        "dashboard": "📊 Dashboard",
        "users": "👥 Users",
        "beta": "🔬 Beta Testers",
        "feedback": "💬 Feedback",
        "billing": "💳 Billing",
        "credits": "🪙 Credits",
        "api_usage": "🤖 API Usage",
        "analytics": "📈 Analytics",
        "audit_log": "📋 Audit Log",
    }
    for key, label in sections.items():
        if st.button(label, use_container_width=True, key=f"nav_{key}"):
            st.session_state.admin_section = key
            st.rerun()

section = st.session_state.admin_section
st.title(f"⚙️ Admin — {sections.get(section, section).split(' ', 1)[-1]}")

# ── Dashboard ─────────────────────────────────────────────────────────────────

if section == "dashboard":
    data, err = admin_get_overview(token)
    if err:
        st.error(f"Failed to load dashboard: {err}")
    elif data:
        users = data.get("users", {})
        feedback = data.get("feedback", {})
        beta_codes = data.get("beta_codes", {})
        ai = data.get("ai_calls_last_30d", 0)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Users", users.get("total", 0))
        col2.metric("Premium Users", users.get("premium", 0))
        col3.metric("Beta Testers", users.get("beta_testers", 0))
        col4.metric("Open Feedback", feedback.get("open", 0))

        col5, col6, col7, col8 = st.columns(4)
        col5.metric("Active Beta Codes", beta_codes.get("active", 0))
        col6.metric("AI Calls (30d)", ai)

        # System health
        st.markdown("---")
        st.markdown("### 🟢 System Status")
        col_h1, col_h2 = st.columns(2)
        col_h1.success("✅ API — Online")
        col_h2.success("✅ Database — Connected")


# ── User Management ───────────────────────────────────────────────────────────

elif section == "users":
    st.markdown("### 👥 User Management")
    search = st.text_input("🔍 Search by name or email", key="user_search")

    users_data, err = admin_get_users(token, search=search, limit=100)
    if err:
        st.error(f"Failed to load users: {err}")
    elif users_data:
        df = pd.DataFrame(users_data)
        display_cols = [c for c in ["id", "email", "display_name", "tier", "is_admin", "beta_tester", "is_active", "created_at"] if c in df.columns]
        st.dataframe(df[display_cols] if display_cols else df, use_container_width=True)

        # Admin actions
        st.markdown("### Actions")
        col1, col2 = st.columns(2)
        with col1:
            user_id = st.number_input("User ID", min_value=1, step=1, key="action_user_id")
        with col2:
            action = st.selectbox("Action", [
                "grant-premium", "revoke-premium",
                "grant-beta", "revoke-beta",
                "suspend", "reactivate",
                "promote-admin", "demote-admin",
            ], key="action_type")

        reason = st.text_input("Reason (optional)", key="action_reason")

        if st.button("✅ Confirm Action", type="primary"):
            if not user_id:
                st.error("Please enter a user ID.")
            else:
                confirmed = st.session_state.get("action_confirmed", False)
                if not confirmed:
                    st.warning(f"⚠️ You are about to **{action}** user #{user_id}. Click again to confirm.")
                    st.session_state.action_confirmed = True
                else:
                    result, err = admin_user_action(token, int(user_id), action, {"reason": reason} if reason else {})
                    st.session_state.action_confirmed = False
                    if err:
                        st.error(f"Action failed: {err}")
                    else:
                        st.success(result.get("message", "Action completed."))

        # Add/remove credits
        st.markdown("### Credit Management")
        cr_col1, cr_col2, cr_col3, cr_col4 = st.columns(4)
        with cr_col1:
            cr_user_id = st.number_input("User ID", min_value=1, step=1, key="cr_user_id")
        with cr_col2:
            cr_type = st.selectbox("Credit Type", ["building", "ai", "commute"], key="cr_type")
        with cr_col3:
            cr_amount = st.number_input("Amount", min_value=1, step=1, key="cr_amount")
        with cr_col4:
            cr_op = st.selectbox("Operation", ["add", "remove"], key="cr_op")

        if st.button("💳 Apply Credits"):
            result, err = admin_user_action(
                token, int(cr_user_id), f"{cr_op}-credits",
                {"credit_type": cr_type, "amount": int(cr_amount)}
            )
            if err:
                st.error(f"Failed: {err}")
            else:
                st.success(result.get("message", "Credits updated."))


# ── Beta Testers ──────────────────────────────────────────────────────────────

elif section == "beta":
    tab1, tab2, tab3 = st.tabs(["Active Beta Users", "Pending Invitations", "Invite New"])

    with tab1:
        beta_users, err = admin_get_beta_users(token)
        if err:
            st.error(f"Failed to load beta users: {err}")
        elif beta_users:
            df = pd.DataFrame(beta_users)
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No active beta testers found.")

    with tab2:
        invitations, err = admin_get_beta_invitations(token)
        if err:
            st.error(f"Failed to load invitations: {err}")
        elif invitations:
            df = pd.DataFrame(invitations)
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No pending invitations.")

    with tab3:
        st.markdown("### Invite Beta Tester")
        with st.form("invite_beta_form"):
            inv_email = st.text_input("Email *", placeholder="user@example.com")
            inv_name = st.text_input("Name (optional)")
            inv_expires = st.date_input("Beta Access Expires")
            inv_building = st.number_input("Building Analyses", min_value=1, value=10, step=1)
            inv_ai = st.number_input("AI Requests", min_value=0, value=50, step=10)
            inv_commute = st.number_input("Commute Calculations", min_value=0, value=20, step=5)
            inv_premium = st.checkbox("Enable Premium Features", value=True)
            submit = st.form_submit_button("📧 Send Invitation", use_container_width=True)

        if submit:
            if not inv_email.strip():
                st.error("Email is required.")
            else:
                result, err = admin_invite_beta(token, {
                    "email": inv_email.strip(),
                    "display_name": inv_name.strip() or None,
                    "expires_at": str(inv_expires),
                    "building_analyses": int(inv_building),
                    "ai_credits": int(inv_ai),
                    "commute_credits": int(inv_commute),
                    "premium_features": inv_premium,
                })
                if err:
                    st.error(f"Invitation failed: {err}")
                else:
                    st.success(f"Invitation sent to {inv_email}! {result.get('message', '')}")


# ── Feedback ──────────────────────────────────────────────────────────────────

elif section == "feedback":
    st.markdown("### 💬 Feedback Management")
    status_filter = st.selectbox("Filter by status", ["", "new", "triaged", "in_progress", "resolved", "closed"])
    feedback_data, err = admin_get_feedback(token, status_filter=status_filter, limit=100)

    if err:
        st.error(f"Failed to load feedback: {err}")
    elif feedback_data:
        df = pd.DataFrame(feedback_data)
        display_cols = [c for c in ["id", "public_reference", "category", "title", "status", "severity", "priority", "created_at"] if c in df.columns]
        st.dataframe(df[display_cols] if display_cols else df, use_container_width=True)

        st.markdown("### Update Feedback")
        with st.form("update_feedback_form"):
            fb_id = st.number_input("Feedback ID", min_value=1, step=1)
            fb_status = st.selectbox("Status", ["new", "triaged", "in_progress", "resolved", "closed", "wont_fix"])
            fb_severity = st.selectbox("Severity", ["", "critical", "high", "medium", "low"])
            fb_priority = st.selectbox("Priority", ["", "urgent", "high", "medium", "low"])
            fb_notes = st.text_area("Internal Notes")
            fb_submit = st.form_submit_button("Update")

        if fb_submit:
            payload = {"status": fb_status}
            if fb_severity:
                payload["severity"] = fb_severity
            if fb_priority:
                payload["priority"] = fb_priority
            if fb_notes:
                payload["internal_notes"] = fb_notes
            result, err = admin_update_feedback(token, int(fb_id), payload)
            if err:
                st.error(f"Update failed: {err}")
            else:
                st.success("Feedback updated.")
    else:
        st.info("No feedback found.")


# ── Billing ───────────────────────────────────────────────────────────────────

elif section == "billing":
    data, err = admin_get_billing(token)
    if err:
        st.error(f"Failed to load billing data: {err}")
    elif data:
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Events", data.get("total_events", 0))
        col2.metric("Revenue (USD)", f"${data.get('total_revenue_usd', 0):.2f}")
        col3.metric("Refunds (USD)", f"${data.get('total_refunds_usd', 0):.2f}")

        events = data.get("recent_events", [])
        if events:
            st.markdown("### Recent Billing Events")
            st.dataframe(pd.DataFrame(events), use_container_width=True)


# ── Credits ───────────────────────────────────────────────────────────────────

elif section == "credits":
    st.markdown("### 🪙 Credit Management")
    st.info("Use the User Management section to add or remove credits for a specific user.")
    st.markdown("Search for a user in **Users**, then use the Credit Management panel there.")


# ── API Usage ─────────────────────────────────────────────────────────────────

elif section == "api_usage":
    days = st.slider("Time period (days)", 7, 90, 30)
    data, err = admin_get_ai_costs(token, days=days)
    if err:
        st.error(f"Failed to load API usage: {err}")
    elif data:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total AI Calls", data.get("total_calls", 0))
        col2.metric("Cache Hits", data.get("cache_hits", 0))
        col3.metric("Estimated Cost", f"${data.get('estimated_cost_usd', 0):.4f}")
        col4.metric("Total Tokens", f"{data.get('total_tokens', 0):,}")


# ── Analytics ─────────────────────────────────────────────────────────────────

elif section == "analytics":
    days = st.slider("Time period (days)", 7, 90, 30, key="analytics_days")
    data, err = admin_get_analytics(token, days=days)
    if err:
        st.error(f"Failed to load analytics: {err}")
    elif data:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("New Users", data.get("new_users", 0))
        col2.metric("Active Users", data.get("active_users", 0))
        col3.metric("Premium Conversions", data.get("premium_conversions", 0))
        col4.metric("Beta Conversions", data.get("beta_conversions", 0))

        growth = data.get("daily_signups", [])
        if growth:
            import pandas as pd
            df = pd.DataFrame(growth)
            if "date" in df.columns and "count" in df.columns:
                st.markdown("### User Growth")
                st.line_chart(df.set_index("date")["count"])


# ── Audit Log ─────────────────────────────────────────────────────────────────

elif section == "audit_log":
    data, err = admin_get_audit_log(token, limit=100)
    if err:
        st.error(f"Failed to load audit log: {err}")
    elif data:
        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No audit log entries found.")
