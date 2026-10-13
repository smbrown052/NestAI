"""Diagnostics must preserve the original failure when browser transport fails."""

from types import SimpleNamespace

from playwright.sync_api import Error

from conftest import browser_text


def test_browser_diagnostics_do_not_mask_transport_failure():
    def disconnected(**kwargs):
        assert kwargs["timeout"] == 3000
        raise Error("read ECONNRESET")

    page = SimpleNamespace(locator=lambda selector: SimpleNamespace(inner_text=disconnected))
    assert browser_text(page) == "Browser diagnostics unavailable: read ECONNRESET"


def test_browser_diagnostics_bound_page_text():
    page = SimpleNamespace(
        locator=lambda selector: SimpleNamespace(inner_text=lambda **kwargs: "x" * 7000)
    )
    assert browser_text(page) == "x" * 6000
