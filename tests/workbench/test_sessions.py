"""Step definitions for Workbench session persistence tests."""

from __future__ import annotations

import time

import pytest
from pytest_bdd import scenario, given, when, then


@scenario("test_sessions.feature", "A new session starts and persists")
def test_session_persists():
    pass


@given("the user is logged in to Workbench")
def user_logged_in(page, workbench_url, test_username, test_password):
    page.goto(workbench_url)
    if "sign-in" in page.url.lower() or "login" in page.url.lower():
        page.fill("#username, [name='username']", test_username)
        page.fill("#password, [name='password']", test_password)
        page.click("button[type='submit'], #sign-in")
        page.wait_for_load_state("networkidle")


@when("the user starts a new session")
def start_session(page):
    page.click("text=New Session", timeout=15000)
    page.click("button:has-text('Start')", timeout=5000)


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
    page.wait_for_load_state("networkidle")
    sessions = page.query_selector_all(".session-row, tr.session, [data-session-id]")
    assert len(sessions) > 0, "No sessions found in the active sessions list"


@then("the session has no error status")
def session_no_error(page):
    # Check that none of the session entries display an error indicator.
    error_indicators = page.query_selector_all(".session-error, .error-badge, .status-error")
    assert len(error_indicators) == 0, "One or more sessions show an error status"
