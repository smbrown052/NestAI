"""
pages/1_Account.py — NestAI user account page.

Shows login, sign-up, password-reset forms, and the authenticated user
dashboard. Requires NESTAI_API_URL to be set in Streamlit secrets.
"""

import streamlit as st

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from auth_client import (
    login,
    register,
    get_me,
    update_profile,
    request_password_reset,
    confirm_password_reset,
)

st.set_page_config(page_title="NestAI — Account", page_icon="👤")
st.title("👤 My Account")

# ── Session state defaults ────────────────────────────────────────────────────

for key, default in {
    "auth_token": None,
    "auth_user": None,
    "acct_view": "login",        # login | register | forgot | confirm_reset | profile
    "acct_message": None,        # (type, text) tuple
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ── Helpers ───────────────────────────────────────────────────────────────────

def _show_message():
    msg = st.session_state.acct_message
    if msg:
        mtype, mtext = msg
        if mtype == "success":
            st.success(mtext)
        elif mtype == "error":
            st.error(mtext)
        elif mtype == "info":
            st.info(mtext)
        st.session_state.acct_message = None


def _set_message(mtype: str, text: str):
    st.session_state.acct_message = (mtype, text)


def _refresh_user():
    """Reload the current user from the API and update session state."""
    data, err = get_me(st.session_state.auth_token)
    if err:
        st.session_state.auth_token = None
        st.session_state.auth_user = None
    else:
        st.session_state.auth_user = data


# ── If already logged in, go straight to profile ─────────────────────────────

if st.session_state.auth_token and st.session_state.acct_view not in ("profile",):
    _refresh_user()
    if st.session_state.auth_user:
        st.session_state.acct_view = "profile"

_show_message()

# ── Login ─────────────────────────────────────────────────────────────────────

if st.session_state.acct_view == "login":
    st.subheader("Sign In")
    with st.form("login_form"):
        email = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Sign In", use_container_width=True)

    if submit:
        if not email.strip() or not password:
            st.error("Please enter your email and password.")
        else:
            data, err = login(email.strip(), password)
            if err:
                st.error(f"Sign in failed: {err}")
            else:
                st.session_state.auth_token = data["access_token"]
                _refresh_user()
                if st.session_state.auth_user:
                    _set_message("success", f"Welcome back, {st.session_state.auth_user.get('display_name') or email}!")
                    st.session_state.acct_view = "profile"
                    st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Create an account", use_container_width=True):
            st.session_state.acct_view = "register"
            st.rerun()
    with col2:
        if st.button("Forgot password?", use_container_width=True):
            st.session_state.acct_view = "forgot"
            st.rerun()


# ── Register ──────────────────────────────────────────────────────────────────

elif st.session_state.acct_view == "register":
    st.subheader("Create Account")
    with st.form("register_form"):
        display_name = st.text_input("Name (optional)", placeholder="Your name")
        email = st.text_input("Email *", placeholder="you@example.com")
        password = st.text_input("Password *", type="password", help="Minimum 8 characters.")
        confirm = st.text_input("Confirm Password *", type="password")
        submit = st.form_submit_button("Create Account", use_container_width=True)

    if submit:
        if not email.strip() or not password:
            st.error("Email and password are required.")
        elif password != confirm:
            st.error("Passwords do not match.")
        elif len(password) < 8:
            st.error("Password must be at least 8 characters.")
        else:
            data, err = register(email.strip(), password, display_name.strip())
            if err:
                st.error(f"Registration failed: {err}")
            else:
                st.session_state.auth_token = data["access_token"]
                _refresh_user()
                _set_message("success", "Account created! Welcome to NestAI.")
                st.session_state.acct_view = "profile"
                st.rerun()

    if st.button("← Back to sign in"):
        st.session_state.acct_view = "login"
        st.rerun()


# ── Forgot password ───────────────────────────────────────────────────────────

elif st.session_state.acct_view == "forgot":
    st.subheader("Reset Password")
    st.write("Enter your email and we'll send you a reset link.")
    with st.form("forgot_form"):
        email = st.text_input("Email", placeholder="you@example.com")
        submit = st.form_submit_button("Send Reset Email", use_container_width=True)

    if submit:
        if not email.strip():
            st.error("Please enter your email address.")
        else:
            data, err = request_password_reset(email.strip())
            if err:
                st.error(f"Error: {err}")
            else:
                _set_message("success", "If an account with that email exists, a reset link has been sent.")
                st.session_state.acct_view = "confirm_reset"
                st.rerun()

    if st.button("← Back to sign in"):
        st.session_state.acct_view = "login"
        st.rerun()


# ── Confirm password reset ────────────────────────────────────────────────────

elif st.session_state.acct_view == "confirm_reset":
    st.subheader("Enter Reset Code")
    with st.form("reset_form"):
        reset_token = st.text_input("Reset token (from your email)", placeholder="Paste the token here")
        new_password = st.text_input("New Password", type="password")
        confirm = st.text_input("Confirm New Password", type="password")
        submit = st.form_submit_button("Reset Password", use_container_width=True)

    if submit:
        if not reset_token.strip() or not new_password:
            st.error("Token and new password are required.")
        elif new_password != confirm:
            st.error("Passwords do not match.")
        elif len(new_password) < 8:
            st.error("Password must be at least 8 characters.")
        else:
            data, err = confirm_password_reset(reset_token.strip(), new_password)
            if err:
                st.error(f"Reset failed: {err}")
            else:
                _set_message("success", "Password reset successfully! Please sign in.")
                st.session_state.acct_view = "login"
                st.rerun()

    if st.button("← Back to sign in"):
        st.session_state.acct_view = "login"
        st.rerun()


# ── Profile / Dashboard ───────────────────────────────────────────────────────

elif st.session_state.acct_view == "profile":
    if not st.session_state.auth_user:
        st.warning("Not signed in.")
        st.session_state.acct_view = "login"
        st.rerun()

    user = st.session_state.auth_user
    _show_message()

    st.subheader(f"Hello, {user.get('display_name') or user.get('email', 'there')} 👋")

    # Account info
    st.markdown("### Account Information")
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Email:** {user.get('email', '—')}")
        st.write(f"**Name:** {user.get('display_name') or '—'}")
        st.write(f"**Plan:** {user.get('tier', 'free').title()}")
        st.write(f"**Beta Tester:** {'✅ Yes' if user.get('beta_tester') else '❌ No'}")
        if user.get("is_admin"):
            st.write("**Role:** 🔑 Administrator")
    with col2:
        joined = user.get("created_at", "—")
        last_login = user.get("last_login")
        premium_exp = user.get("premium_expiration")
        st.write(f"**Member Since:** {str(joined)[:10] if joined else '—'}")
        st.write(f"**Last Login:** {str(last_login)[:10] if last_login else '—'}")
        if premium_exp:
            st.write(f"**Premium Expires:** {str(premium_exp)[:10]}")

    # Credits / usage
    credits = user.get("credits", {})
    if credits:
        st.markdown("### Usage & Credits")
        u1, u2, u3 = st.columns(3)
        with u1:
            st.metric(
                "Building Analyses",
                f"{credits.get('building_credits_remaining', 0)} remaining",
                delta=f"{credits.get('building_credits_used', 0)} used",
            )
        with u2:
            st.metric(
                "AI Requests",
                f"{credits.get('ai_credits_remaining', 0)} remaining",
                delta=f"{credits.get('ai_credits_used', 0)} used",
            )
        with u3:
            st.metric(
                "Commute Calculations",
                f"{credits.get('commute_credits_remaining', 0)} remaining",
                delta=f"{credits.get('commute_credits_used', 0)} used",
            )

    # Edit profile
    st.markdown("### Edit Profile")
    with st.form("edit_profile_form"):
        new_name = st.text_input("Display Name", value=user.get("display_name") or "")
        save = st.form_submit_button("Save Changes")

    if save:
        data, err = update_profile(st.session_state.auth_token, display_name=new_name.strip())
        if err:
            st.error(f"Failed to update: {err}")
        else:
            _refresh_user()
            st.success("Profile updated.")

    # Sign out
    st.divider()
    if st.button("🚪 Sign Out", use_container_width=False):
        st.session_state.auth_token = None
        st.session_state.auth_user = None
        st.session_state.acct_view = "login"
        st.rerun()
