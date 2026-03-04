"""Step definitions for Workbench session persistence tests."""

from __future__ import annotations

import time

import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_sessions.feature", "A new session starts and persists")
def test_session_persists():
    pass


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
            pytest.skip(
                "Interactive auth storage state did not authenticate Workbench. "
                "The OIDC session may not be shared between Connect and Workbench."
            )
        page.fill("#username, [name='username']", test_username)
        page.fill("#password, [name='password']", test_password)
        page.click("button[type='submit'], #sign-in")
        page.wait_for_load_state("load")


@when("the user starts a new session")
def start_session(page):
    page.get_by_role("button", name="New Session").click(timeout=15000)
    page.get_by_role("button", name="Launch").click(timeout=5000)


@when("waits for the session to be ready")
def wait_for_session(page):
    page.wait_for_selector(
        "iframe, .session-frame",
        timeout=60000,
    )
    # Allow a brief settle time.
    time.sleep(3)


@then("the session appears in the active sessions list")
def session_in_list(page, workbench_url):
    # Navigate back to the home page to see the sessions list.
    page.goto(workbench_url)
    page.wait_for_load_state("load")
    sessions = page.query_selector_all(".session-row, tr.session, [data-session-id]")
    assert len(sessions) > 0, "No sessions found in the active sessions list"


@then("the session has no error status")
def session_no_error(page):
    # Check that none of the session entries display an error indicator.
    error_indicators = page.query_selector_all(".session-error, .error-badge, .status-error")
    assert len(error_indicators) == 0, "One or more sessions show an error status"
