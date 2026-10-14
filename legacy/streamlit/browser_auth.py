"""Restore only through a dedicated, server-revocable tab credential."""

from pathlib import Path
from uuid import uuid4

import streamlit as st
import streamlit.components.v1 as components

_storage = components.declare_component("nestai_browser_session", path=str(Path(__file__).parent / "browser_session"))


def sync_browser_session(auth):
    state = st.session_state
    command = state.setdefault("browser_auth_command", {"action": "read", "operation": uuid4().hex})
    result = _storage(**command, key="browser_auth_storage", default=None)
    if not isinstance(result, dict) or result.get("operation") != command["operation"]:
        st.stop()
    if not result.get("available"):
        st.warning("Browser storage is unavailable. Sign-in will last until this page reloads.")
    credential = result.get("credential")
    if command["action"] == "read" and credential and not state.get("auth_token"):
        response = auth.api_client.request("POST", "/auth/restore", json={"credential": credential})
        if response.status_code == 200:
            body = response.json()
            auth.set_authenticated(body["access_token"], body["user"])
            state["browser_auth_credential"] = credential
            state["main_nav"] = "Apartment Search"
        elif response.status_code not in {401, 403, 422}:
            st.error("Account services are temporarily unavailable. Reload to retry sign-in restoration.")
            st.stop()
        else:
            state["browser_auth_command"] = {"action": "clear", "operation": uuid4().hex}
            st.rerun()


def persist_browser_session(auth):
    state = st.session_state
    if not state.get("auth_token") or state.get("browser_auth_credential"):
        return
    response = auth.api_client.request("POST", "/auth/browser-session")
    if response.status_code != 200:
        st.warning("Automatic sign-in restoration is unavailable. Your saved data is unchanged.")
        return
    credential = response.json()["credential"]
    state["browser_auth_credential"] = credential
    state["browser_auth_command"] = {
        "action": "write", "credential": credential, "operation": uuid4().hex,
    }
    st.rerun()
