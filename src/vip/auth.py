"""Interactive browser authentication for OIDC providers."""

from __future__ import annotations

import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


def run_interactive_auth(connect_url: str) -> Path:
    """Launch a headed browser, navigate to Connect login, wait for
    the user to authenticate, and save the storage state.

    Returns the path to a temporary JSON file containing the storage state.
    """
    storage_state_path = Path(tempfile.mkdtemp()) / "vip-auth-state.json"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # Navigate to Connect login page — this will redirect to the IdP
        page.goto(f"{connect_url}/__login__")

        # Wait for the user to complete authentication.
        # After OIDC flow, the user lands back on Connect (not the login page).
        # We poll until the URL no longer contains /__login__ and is back on
        # the connect_url domain, with a generous timeout.
        print(f"\n>>> A browser window has opened at {connect_url}")
        print(">>> Please log in through your identity provider.")
        print(">>> The browser will close automatically once login is complete.\n")

        # Wait for redirect back to Connect after login (up to 5 minutes)
        page.wait_for_url(
            lambda url: connect_url.rstrip("/") in url and "/__login__" not in url,
            timeout=300_000,
        )

        # Save storage state (cookies + localStorage)
        context.storage_state(path=str(storage_state_path))
        browser.close()

    return storage_state_path
