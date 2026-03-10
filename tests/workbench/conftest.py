"""Workbench-specific fixtures and helpers.

Page selectors are in the pages/ subpackage
"""

from __future__ import annotations

import time

import pytest
from playwright.sync_api import Page, expect

from tests.workbench.pages import Homepage, LoginPage, NewSessionDialog

pytestmark = pytest.mark.workbench

# Keywords indicating the URL is a login/auth page (used for OIDC detection)
_LOGIN_KEYWORDS = ("sign-in", "login", "auth")


def _on_login_page(url: str) -> bool:
    """Return True if *url* looks like a login or IdP page."""
    lower = url.lower()
    return any(kw in lower for kw in _LOGIN_KEYWORDS)


# ---------------------------------------------------------------------------
# Login Helper
# ---------------------------------------------------------------------------


def workbench_login(
    page: Page,
    workbench_url: str,
    username: str,
    password: str,
    auth_provider: str = "password",
    interactive_auth: bool = False,
    *,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> None:
    """Navigate to Workbench homepage, logging in only if required.

    This function:
    - Navigates directly to Workbench's URL
    - Handles OIDC/SSO via --interactive-auth storage state
    - Only fills login form for password auth
    - Retries on transient server errors (e.g., too many logins)

    Args:
        page: Playwright page object
        workbench_url: Base URL for Workbench (e.g., http://localhost:8787)
        username: Login username
        password: Login password
        auth_provider: Auth type (e.g., "password", "oidc", "saml")
        interactive_auth: True if --interactive-auth was used (browser has storage state)
        max_retries: Max login attempts on transient errors (default 3)
        retry_delay: Seconds to wait between retries (default 2.0)

    Raises:
        pytest.skip: For non-password auth without interactive_auth, or when
            interactive_auth storage state doesn't cover Workbench
        AssertionError: When password login fails after retries
    """
    homepage_logo = page.locator(Homepage.POSIT_LOGO)

    # For non-password auth without interactive auth, skip immediately
    if auth_provider != "password" and not interactive_auth:
        pytest.skip(
            f"Login form not available for auth provider {auth_provider!r}. "
            "Pass --interactive-auth when browser storage state is pre-loaded."
        )

    page.goto(workbench_url)
    page.wait_for_load_state("load")

    # Fast path: already logged in (common with interactive_auth)?
    if homepage_logo.is_visible():
        return

    # Check if we landed on a login/IdP page
    if _on_login_page(page.url):
        if auth_provider != "password":
            # Interactive auth storage state didn't authenticate Workbench
            pytest.skip(
                "Interactive auth storage state did not authenticate Workbench. "
                "The OIDC session may not be shared between Connect and Workbench."
            )
        # Password auth - proceed with form login below
    else:
        # Not on homepage, not on login page - unexpected state
        # Give it one more check in case page is still loading
        try:
            homepage_logo.wait_for(state="visible", timeout=5000)
            return
        except Exception:
            pass

    # Password authentication with retry logic
    login_form = page.locator(LoginPage.USERNAME)
    error_panel = page.locator(LoginPage.ERROR_PANEL)

    for attempt in range(max_retries):
        if attempt > 0:
            time.sleep(retry_delay)
            page.goto(workbench_url)

        # Fast path check on retry
        if homepage_logo.is_visible():
            return

        # Wait for login form to be ready
        try:
            login_form.wait_for(state="visible", timeout=5000)
        except Exception:
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


@pytest.fixture(autouse=True)
def _cleanup_sessions(page, workbench_client):
    """Quit any Workbench sessions created during the test."""
    yield
    if workbench_client is None:
        return
    try:
        cookies = {c["name"]: c["value"] for c in page.context.cookies()}
        workbench_client.set_cookies(cookies)
        sessions = workbench_client.list_sessions()
        for session in sessions:
            sid = session.get("id") or session.get("session_id", "")
            if sid:
                workbench_client.quit_session(sid)
    except Exception:
        # Best-effort cleanup; don't mask test failures.
        pass


@pytest.fixture
def wb_login(
    page: Page,
    workbench_url: str,
    test_username: str,
    test_password: str,
    auth_provider: str,
    interactive_auth: bool,
):
    """Log in to Workbench and verify homepage loads.

    This fixture handles the complete login flow using rstudio-pro patterns.
    Handles password auth, OIDC via --interactive-auth, and skips gracefully
    when auth type is unsupported.

    Returns the page for further interactions.
    """
    workbench_login(
        page, workbench_url, test_username, test_password, auth_provider, interactive_auth
    )

    # Verify homepage elements (use .first for NEW_SESSION_BUTTON as there can be two)
    expect(page.locator(Homepage.POSIT_LOGO)).to_be_visible(timeout=15000)
    expect(page.locator(Homepage.NEW_SESSION_BUTTON).first).to_be_visible(timeout=15000)

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

        page.locator(Homepage.NEW_SESSION_BUTTON).first.click(timeout=10000)

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
