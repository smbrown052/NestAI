"""Browser-storage synchronization must fail closed without losing recoverable state."""

from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import browser_auth


class Halt(Exception):
    pass


@pytest.fixture
def lifecycle(monkeypatch):
    state = {"browser_auth_command": {"action": "read", "operation": "read-1"}}
    ui = SimpleNamespace(session_state=state, warning=Mock(), error=Mock(),
                         stop=Mock(side_effect=Halt), rerun=Mock(side_effect=Halt))
    storage = Mock(return_value={"operation": "read-1", "credential": "opaque", "available": True})
    auth = Mock()
    auth.api_client.request.return_value = SimpleNamespace(
        status_code=200, json=lambda: {"access_token": "access", "user": {"id": 4}},
    )
    monkeypatch.setattr(browser_auth, "st", ui)
    monkeypatch.setattr(browser_auth, "_storage", storage)
    return state, ui, storage, auth


def test_restore_waits_for_current_storage_acknowledgement(lifecycle):
    state, ui, storage, auth = lifecycle
    storage.return_value["operation"] = "previous"
    with pytest.raises(Halt):
        browser_auth.sync_browser_session(auth)
    auth.api_client.request.assert_not_called()


def test_restore_uses_only_validated_api_identity(lifecycle):
    state, ui, storage, auth = lifecycle
    browser_auth.sync_browser_session(auth)
    auth.set_authenticated.assert_called_once_with("access", {"id": 4})
    assert state["browser_auth_credential"] == "opaque"
    assert state["main_nav"] == "Apartment Search"


@pytest.mark.parametrize("status", [0, 429, 500, 503])
def test_outage_does_not_discard_restoration_credential(lifecycle, status):
    state, ui, storage, auth = lifecycle
    auth.api_client.request.return_value.status_code = status
    with pytest.raises(Halt):
        browser_auth.sync_browser_session(auth)
    assert state["browser_auth_command"]["action"] == "read"
    auth.set_authenticated.assert_not_called()
    ui.error.assert_called_once()


@pytest.mark.parametrize("status", [401, 403, 422])
def test_invalid_restoration_is_cleared_before_rendering(lifecycle, status):
    state, ui, storage, auth = lifecycle
    auth.api_client.request.return_value.status_code = status
    with pytest.raises(Halt):
        browser_auth.sync_browser_session(auth)
    assert state["browser_auth_command"]["action"] == "clear"
    auth.set_authenticated.assert_not_called()


def test_unavailable_storage_does_not_claim_restoration(lifecycle):
    state, ui, storage, auth = lifecycle
    storage.return_value.update(available=False, credential=None)
    browser_auth.sync_browser_session(auth)
    ui.warning.assert_called_once()
    auth.set_authenticated.assert_not_called()


def test_authenticated_session_issues_one_dedicated_credential(lifecycle):
    state, ui, storage, auth = lifecycle
    state["auth_token"] = "access"
    auth.api_client.request.return_value.json = lambda: {"credential": "dedicated"}
    with pytest.raises(Halt):
        browser_auth.persist_browser_session(auth)
    assert state["browser_auth_command"]["action"] == "write"
    assert state["browser_auth_command"]["credential"] == "dedicated"
    browser_auth.persist_browser_session(auth)
    auth.api_client.request.assert_called_once_with("POST", "/auth/browser-session")


def test_account_switch_revokes_previous_restoration_and_clears_private_state():
    from auth_service import StreamlitAuthManager

    state = {
        "auth_user": {"id": 1}, "auth_token": "old-access",
        "browser_auth_credential": "old-restoration", "account_analytics": {"private": True},
    }
    client = Mock()
    auth = StreamlitAuthManager(client, state=state)
    auth.set_authenticated("new-access", {"id": 2, "tier": "free"})
    client.request.assert_called_once_with(
        "POST", "/auth/revoke-browser-session", json={"credential": "old-restoration"},
    )
    assert "browser_auth_credential" not in state
    assert "account_analytics" not in state
    assert state["auth_user"]["id"] == 2
    assert state["browser_auth_command"]["action"] == "clear"
