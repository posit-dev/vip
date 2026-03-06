"""Workbench-specific fixtures and helpers.

Page selectors are in the pages/ subpackage, organized to mirror rstudio-pro/e2e/pages/.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.workbench.pages import Homepage, LoginPage, NewSessionDialog

if TYPE_CHECKING:
    pass

pytestmark = pytest.mark.workbench


# ---------------------------------------------------------------------------
# Login Helper
# ---------------------------------------------------------------------------


def workbench_login(
    page: Page,
    workbench_url: str,
    username: str,
    password: str,
    *,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> None:
    """Navigate to Workbench homepage, logging in only if required.

    This function:
    - Navigates directly to /home to reuse existing sessions
    - Only logs in if redirected to the login page
    - Retries on transient server errors (e.g., too many logins)

    Args:
        page: Playwright page object
        workbench_url: Base URL for Workbench (e.g., http://localhost:8787)
        username: Login username
        password: Login password
        max_retries: Max login attempts on transient errors (default 3)
        retry_delay: Seconds to wait between retries (default 2.0)
    """
    home_url = workbench_url.rstrip("/") + "/home"
    homepage_logo = page.locator(Homepage.POSIT_LOGO)
    login_form = page.locator(LoginPage.USERNAME)
    error_panel = page.locator(LoginPage.ERROR_PANEL)

    for attempt in range(max_retries):
        if attempt > 0:
            time.sleep(retry_delay)

        page.goto(home_url)

        # Fast path: already logged in?
        if homepage_logo.is_visible():
            return

        # Need to login - wait for form to be ready
        try:
            login_form.wait_for(state="visible", timeout=5000)
        except Exception:
            # Neither homepage nor login visible - unexpected state, retry
            continue

        # Fill and submit
        page.fill(LoginPage.USERNAME, username)
        page.fill(LoginPage.PASSWORD, password)

        stay_signed_in = page.locator(LoginPage.STAY_SIGNED_IN)
        if stay_signed_in.is_visible() and not stay_signed_in.is_checked():
            stay_signed_in.click()

        page.click(LoginPage.BUTTON)

        # Wait for either homepage (success) or error panel (failure)
        homepage_or_error = homepage_logo.or_(error_panel)
        try:
            homepage_or_error.wait_for(state="visible", timeout=15000)
        except Exception:
            if attempt == max_retries - 1:
                raise AssertionError(f"Login failed after {max_retries} attempts: no response")
            continue

        # Check which one appeared
        if homepage_logo.is_visible():
            return  # Success!

        # Error appeared - extract message and maybe retry
        if attempt == max_retries - 1:
            error_text = page.locator(LoginPage.ERROR_TEXT).text_content()
            raise AssertionError(f"Login failed: {error_text or 'Unknown error'}")
        # Transient error (e.g., rate limit) - retry

    raise AssertionError(f"Login failed after {max_retries} attempts")


# ---------------------------------------------------------------------------
# Shared Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def wb_login(page: Page, workbench_url: str, test_username: str, test_password: str):
    """Log in to Workbench and verify homepage loads.

    This fixture handles the complete login flow using rstudio-pro patterns.
    Handles both fresh login and already-authenticated sessions.
    Returns the page for further interactions.
    """
    workbench_login(page, workbench_url, test_username, test_password)

    # Verify homepage elements
    expect(page.locator(Homepage.POSIT_LOGO)).to_be_visible(timeout=15000)
    expect(page.locator(Homepage.NEW_SESSION_BUTTON)).to_be_visible(timeout=15000)

    return page


@pytest.fixture
def wb_start_session(page: Page, wb_login):
    """Factory fixture to start a session of any IDE type.

    Usage:
        def test_example(wb_start_session):
            session_name = wb_start_session("RStudio")

            # Or with auto_join disabled to stay on homepage:
            session_name = wb_start_session("RStudio", auto_join=False)
    """

    def _start(ide_type: str, session_name: str | None = None, *, auto_join: bool = True) -> str:
        if session_name is None:
            session_name = f"VIP Test {ide_type} {int(time.time())}"

        page.locator(Homepage.NEW_SESSION_BUTTON).click(timeout=10000)

        # Wait for dialog to appear
        dialog = page.locator(NewSessionDialog.DIALOG)
        expect(dialog.locator(NewSessionDialog.TITLE)).to_have_text("New Session", timeout=10000)

        # Select IDE type using role-based selector within dialog
        ide_display = NewSessionDialog.ide_display_name(ide_type)
        dialog.get_by_role("tab", name=ide_display).click(timeout=5000)

        # Set session name
        page.fill(NewSessionDialog.SESSION_NAME, session_name)

        # Set auto-join checkbox based on parameter
        checkbox = page.locator(NewSessionDialog.JOIN_CHECKBOX)
        if auto_join and not checkbox.is_checked():
            checkbox.click()
        elif not auto_join and checkbox.is_checked():
            checkbox.click()

        # Launch the session
        page.locator(NewSessionDialog.LAUNCH_BUTTON).click(timeout=5000)

        # Wait for session to become active
        expect(page.get_by_text(session_name, exact=True)).to_be_visible(timeout=15000)
        expect(page.get_by_role("button", name="Active").first).to_be_visible(timeout=90000)

        return session_name

    return _start


@pytest.fixture
def wb_quit_session(page: Page):
    """Factory fixture to quit a session by name."""

    def _quit(session_name: str):
        checkbox = page.locator(Homepage.session_checkbox(session_name))
        checkbox.click()

        quit_btn = page.locator(Homepage.QUIT_BUTTON)
        expect(quit_btn).to_be_visible()
        quit_btn.click()

        # Wait for session to disappear
        expect(page.locator(Homepage.session_link(session_name))).not_to_be_visible(timeout=30000)

    return _quit
