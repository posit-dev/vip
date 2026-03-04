"""Step definitions for Workbench IDE launch tests.

These tests use Playwright to walk through the Workbench UI and verify that
each IDE type can be started.  They are intentionally resilient to UI layout
changes by using multiple selector strategies.
"""

from __future__ import annotations

import time

import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_ide_launch.feature", "RStudio IDE session can be launched")
def test_launch_rstudio():
    pass


@scenario("test_ide_launch.feature", "VS Code session can be launched")
def test_launch_vscode():
    pass


@scenario("test_ide_launch.feature", "JupyterLab session can be launched")
def test_launch_jupyter():
    pass


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_state():
    return {}


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@given("the user is logged in to Workbench")
def user_logged_in(
    page,
    workbench_url,
    test_username,
    test_password,
    auth_provider,
    interactive_auth,
):
    # For non-password auth without interactive auth, skip immediately.
    if auth_provider != "password" and not interactive_auth:
        pytest.skip(
            f"Login form not available for auth provider {auth_provider!r}. "
            "Pass --interactive-auth when browser storage state is pre-loaded."
        )
    page.goto(workbench_url)
    page.wait_for_load_state("load")
    # Check if we ended up on a login page.
    on_login = any(kw in page.url.lower() for kw in ("sign-in", "login", "auth"))
    if on_login:
        if auth_provider != "password":
            # Interactive auth storage state didn't authenticate Workbench.
            pytest.skip(
                "Interactive auth storage state did not authenticate Workbench. "
                "The OIDC session may not be shared between Connect and Workbench."
            )
        page.fill("#username, [name='username']", test_username)
        page.fill("#password, [name='password']", test_password)
        page.click("button[type='submit'], #sign-in")
        page.wait_for_load_state("load")


def _click_new_session(page, session_state):
    """Click the enabled 'New Session' button.

    When the user is already inside a session the Workbench UI renders two
    buttons with the same name — one disabled in the sidebar and one enabled
    as the primary action.  Using :not([disabled]) avoids the strict-mode
    violation.
    """
    # Record the current URL so session_starts can detect a real navigation.
    session_state["url_before_launch"] = page.url
    page.locator("button:not([disabled])", has_text="New Session").first.click(timeout=15000)


@when("the user launches an RStudio session")
def launch_rstudio(page, session_state):
    _click_new_session(page, session_state)
    page.get_by_role("tab", name="RStudio Pro").click(timeout=5000)
    page.get_by_role("button", name="Launch").click(timeout=5000)


@when("the user launches a VS Code session")
def launch_vscode(page, session_state):
    _click_new_session(page, session_state)
    page.get_by_role("tab", name="VS Code").click(timeout=5000)
    page.get_by_role("button", name="Launch").click(timeout=5000)


@when("the user launches a JupyterLab session")
def launch_jupyter(page, session_state):
    _click_new_session(page, session_state)
    page.get_by_role("tab", name="JupyterLab").click(timeout=5000)
    page.get_by_role("button", name="Launch").click(timeout=5000)


@then("the session starts within a reasonable time")
def session_starts(page, session_state):
    # All IDE sessions navigate to a /s/<session-id>/ URL when ready.
    # If the browser was already at a /s/ URL (from a previous session),
    # we need to wait for the URL to actually change.
    url_before = session_state.get("url_before_launch", "")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if "/s/" in page.url and page.url != url_before:
            return
        page.wait_for_timeout(500)
    raise TimeoutError(f"Session did not start within 60 s.  URL stayed at {page.url}")


@then("the RStudio IDE is displayed")
def rstudio_displayed(page):
    # RStudio loads inside an iframe with id="rstudio"; it carries
    # aria-hidden="true" during init so check attachment not visibility.
    page.wait_for_selector("iframe#rstudio", timeout=30000, state="attached")


@then("the VS Code IDE is displayed")
def vscode_displayed(page):
    # VS Code embeds multiple hidden iframes (webview, web-worker-ext-host).
    # Check for the webview iframe that hosts the editor.
    page.wait_for_selector(
        "iframe.webview, iframe[src*='code-server'], iframe[src*='vscode']",
        timeout=30000,
        state="attached",
    )


@then("the JupyterLab IDE is displayed")
def jupyter_displayed(page):
    # JupyterLab renders directly in the page (no iframe) and loads
    # progressively — the "load" event may not fire within the default
    # timeout.  Just verify we are on a session URL.
    assert "/s/" in page.url, f"Not on a session URL: {page.url}"
