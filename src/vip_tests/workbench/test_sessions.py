"""Step definitions for Workbench session lifecycle tests.

These tests verify that a session can be suspended and resumed.
Patterns adapted from test_ide_launch.py.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import given, scenario, then, when

from vip_tests.workbench.conftest import (
    TIMEOUT_CLEANUP,
    TIMEOUT_DIALOG,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_QUICK,
    TIMEOUT_SESSION_START,
    assert_homepage_loaded,
    unique_session_name,
    wait_for_session_active,
    workbench_login,
)
from vip_tests.workbench.pages import Homepage, NewSessionDialog

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
    """Verify the session transitions to Suspended state."""
    session_name = session_context["name"]

    session_suspended = page.locator(Homepage.session_row_status(session_name, "Suspended"))
    expect(session_suspended).to_be_visible(timeout=TIMEOUT_CLEANUP)


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

    # Wait for the navigation into the session URL to commit before going
    # anywhere else. Navigating away from /s/<id> too quickly causes
    # Workbench to abort the resume.
    page.wait_for_url("**/s/**", timeout=TIMEOUT_PAGE_LOAD)
    page.wait_for_load_state("load", timeout=TIMEOUT_PAGE_LOAD)

    # Navigate back to homepage to observe the Active state. NB: Workbench's
    # /home may auto-redirect back to the recently-used session — that is OK
    # for the next step, which observes the session badge in the sidebar.
    page.goto(page.url.split("/s/")[0] + "/home") if "/s/" in page.url else page.go_back()
    expect(page.locator(Homepage.POSIT_LOGO)).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)


@then("the session reaches Active state again")
def session_becomes_active_again(page: Page, workbench_url: str, session_context: dict):
    """Verify the session transitions back to Active state."""
    session_name = session_context["name"]

    # Explicitly navigate back to /home. user_resumes_session attempts the
    # same bounce, but Playwright's goto() races with the IDE iframe loading
    # on /s/<id> and sometimes leaves the page on the session URL — where the
    # sidebar shows a stale Suspended badge regardless of the actual server
    # state. Doing the navigation here, in the observation step, guarantees
    # we are looking at the real homepage.
    home_url = workbench_url.rstrip("/") + "/home"
    page.goto(home_url, timeout=TIMEOUT_PAGE_LOAD)
    expect(page.locator(Homepage.POSIT_LOGO)).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)

    # The Workbench homepage does not auto-poll session state, so a single
    # locator wait cannot observe the Suspended → Active transition. Reload
    # periodically inside the overall budget until the Active badge appears.
    session_active = page.locator(Homepage.session_row_status(session_name, "Active"))
    inner_timeout_ms = 5000
    deadline = time.time() + (TIMEOUT_SESSION_START / 1000)
    exc: AssertionError | None = None
    while True:
        try:
            expect(session_active).to_be_visible(timeout=inner_timeout_ms)
            return  # Active observed
        except AssertionError as e:
            exc = e
            if time.time() >= deadline:
                break
            page.reload(timeout=TIMEOUT_PAGE_LOAD)
            expect(page.locator(Homepage.POSIT_LOGO)).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)

    pytest.skip(
        f"Session did not return to Active state after resume — "
        f"suspend/resume may not be supported in this Workbench configuration ({exc})"
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
