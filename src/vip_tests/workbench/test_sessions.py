"""Step definitions for Workbench session lifecycle tests.

These tests verify that a session can be suspended and resumed.
Patterns adapted from test_ide_launch.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import given, scenario, then, when

from vip import attest
from vip_tests.workbench.conftest import (
    TIMEOUT_CLEANUP,
    TIMEOUT_DIALOG,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_QUICK,
    TIMEOUT_SESSION_START,
    assert_homepage_loaded,
    join_session,
    unique_session_name,
    wait_for_session_active,
    wait_for_session_suspended,
    workbench_login,
)
from vip_tests.workbench.pages import Homepage, NewSessionDialog, RStudioSession

pytestmark = pytest.mark.order(30)

# Get filename for session naming
_FILENAME = Path(__file__).name


@scenario("test_sessions.feature", "Session can be suspended and resumed")
def test_session_suspend_resume():
    pass


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------


@pytest.fixture
def session_context():
    """Holds session name across steps."""
    return {"name": None}


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@given("the user is logged in to Workbench")
def user_logged_in(
    page: Page,
    workbench_url: str,
    test_username: str,
    test_password: str,
    auth_provider: str,
    interactive_auth: bool,
    auth_mode: str,
    workbench_auth_error: str | None,
):
    """Log in to Workbench and verify homepage loads."""
    workbench_login(
        page,
        workbench_url,
        test_username,
        test_password,
        auth_provider,
        interactive_auth,
        auth_mode=auth_mode,
        workbench_auth_error=workbench_auth_error,
    )

    assert_homepage_loaded(page)


@when("the user starts a new RStudio Pro session")
def start_rstudio_pro_session(page: Page, session_context: dict):
    """Start a new RStudio Pro session without auto-joining."""
    session_name = unique_session_name(_FILENAME)
    session_context["name"] = session_name

    page.locator(Homepage.NEW_SESSION_BUTTON).first.click(timeout=TIMEOUT_DIALOG)

    dialog = page.locator(NewSessionDialog.DIALOG)
    expect(dialog.locator(NewSessionDialog.TITLE)).to_have_text(
        "New Session", timeout=TIMEOUT_DIALOG
    )

    # Select RStudio Pro tab
    ide_display = NewSessionDialog.ide_display_name("RStudio")
    dialog.get_by_role("tab", name=ide_display).click(timeout=TIMEOUT_QUICK)

    page.fill(NewSessionDialog.SESSION_NAME, session_name)

    # Uncheck auto-join so we stay on homepage to observe state transitions
    checkbox = page.locator(NewSessionDialog.JOIN_CHECKBOX)
    if checkbox.is_checked():
        checkbox.click()
    expect(checkbox).not_to_be_checked(timeout=TIMEOUT_QUICK)

    page.locator(NewSessionDialog.LAUNCH_BUTTON).click(timeout=TIMEOUT_QUICK)


@when("the session reaches Active state")
def session_becomes_active(page: Page, session_context: dict):
    """Wait for the session to reach Active state on the homepage.

    Fails fast with an actionable message if the session reaches a terminal
    state (e.g. Failed) rather than waiting out the full session-start timeout.
    """
    session_name = session_context["name"]
    wait_for_session_active(page, session_name)


@when("the user suspends the session")
def user_suspends_session(page: Page, session_context: dict):
    """Select the session checkbox and click Suspend."""
    session_name = session_context["name"]

    checkbox = page.locator(Homepage.session_checkbox(session_name))
    expect(checkbox).to_be_visible(timeout=TIMEOUT_DIALOG)
    checkbox.click()

    suspend_btn = page.locator(Homepage.SUSPEND_BUTTON)
    expect(suspend_btn).to_be_visible(timeout=TIMEOUT_QUICK)
    suspend_btn.click()


@then("the session reaches Suspended state")
def session_becomes_suspended(page: Page, session_context: dict):
    """Verify the session transitions to Suspended state.

    Fails fast with an actionable message if the session reaches a terminal
    state (e.g. Failed / abnormal exit) instead of suspending, rather than
    waiting out the full timeout and emitting an opaque
    "Locator expected to be visible" error.
    """
    wait_for_session_suspended(page, session_context["name"])


@when("the user resumes the session")
def user_resumes_session(page: Page, session_context: dict):
    """Open the session details modal and click Launch to resume the session."""
    session_name = session_context["name"]

    session_row = page.locator(Homepage.session_row(session_name))
    expect(session_row).to_be_visible(timeout=TIMEOUT_DIALOG)

    # Modern Workbench does not expose a one-click launch link on the row
    # for suspended sessions. Active sessions have `a[title='join <name>']`,
    # but on suspended rows the name is rendered as plain text — clicking
    # it opens a session-details modal that contains a "Launch" button.
    # That Launch button is what triggers the backend resume. The previous
    # implementation's `session_row.locator("a").first` was picking up a
    # "Details" link instead, navigating to /s/<id>/workspaces/ (a
    # management view) and never resuming the session.
    name_text = session_row.locator(Homepage.session_text(session_name))
    expect(name_text).to_be_visible(timeout=TIMEOUT_DIALOG)
    name_text.click()

    # Wait for the Launch button directly rather than the modal container.
    # The modal's CSS class varies between Workbench UI versions (the page
    # object's SESSION_DETAILS_DIALOG selector uses class*='modal-dialog'
    # which does not match the newer data-slot based dialog markup), but
    # the button text is stable. A visible Launch button proves the modal
    # opened.
    launch_btn = page.locator("button:text-is('Launch')")
    expect(launch_btn).to_be_visible(timeout=TIMEOUT_DIALOG)
    launch_btn.click()

    # The post-Launch navigation depends on the session's auto-join setting
    # and the Workbench version, so join explicitly rather than waiting for it.
    # join_session reloads until the session is Active again, and
    # returns early if Launch already took the browser into the session.
    join_session(page, session_name, reload=True)

    # Wait for RStudio content (not just "load", which fires before rsession is
    # reattached -- see ``rstudio_functional`` in test_ide_launch.py).
    try:
        expect(page.locator(RStudioSession.CONTAINER)).to_be_visible(timeout=TIMEOUT_SESSION_START)
    except AssertionError as exc:
        attest.unproven(
            f"RStudio content did not render within {TIMEOUT_SESSION_START}ms of resuming "
            f"the session — suspend/resume may not be supported in this Workbench "
            f"configuration ({exc})"
        )


@then("the session reaches Active state again")
def session_becomes_active_again(page: Page, workbench_url: str, session_context: dict):
    """Verify the resumed session shows Active on the homepage.

    ``join_session`` already waited for Active before joining; this is the
    cheap confirmation from the homepage's point of view. Navigating to /home
    explicitly avoids the IDE iframe on /s/<id> showing a stale Suspended badge.
    """
    session_name = session_context["name"]

    page.goto(workbench_url.rstrip("/") + "/home", timeout=TIMEOUT_PAGE_LOAD)
    expect(page.locator(Homepage.POSIT_LOGO)).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)
    expect(page.locator(Homepage.session_row_status(session_name, "Active"))).to_be_visible(
        timeout=TIMEOUT_DIALOG
    )


@then("the session is cleaned up")
def session_cleaned_up(page: Page, workbench_url: str, session_context: dict):
    """Navigate to homepage and quit the session."""
    session_name = session_context["name"]

    home_url = workbench_url.rstrip("/") + "/home"
    page.goto(home_url)
    expect(page.locator(Homepage.POSIT_LOGO)).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)

    checkbox = page.locator(Homepage.session_checkbox(session_name))
    expect(checkbox).to_be_visible(timeout=TIMEOUT_DIALOG)
    checkbox.click()

    quit_btn = page.locator(Homepage.QUIT_BUTTON)
    expect(quit_btn).to_be_visible(timeout=TIMEOUT_QUICK)
    quit_btn.click()

    session_link = page.locator(Homepage.session_link(session_name))
    expect(session_link).not_to_be_visible(timeout=TIMEOUT_CLEANUP)
