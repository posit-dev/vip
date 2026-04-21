"""Workbench-specific fixtures and helpers.

Page selectors are in the pages/ subpackage
"""

from __future__ import annotations

import time

import httpx
import pytest
from playwright.sync_api import Page, expect

from vip_tests.workbench.pages import Homepage, LoginPage

pytestmark = pytest.mark.workbench

# ---------------------------------------------------------------------------
# Playwright timeout constants (milliseconds)
# ---------------------------------------------------------------------------

TIMEOUT_QUICK = 5_000
TIMEOUT_DIALOG = 10_000
TIMEOUT_PAGE_LOAD = 15_000
TIMEOUT_CLEANUP = 30_000
TIMEOUT_CODE_EXEC = 30_000
TIMEOUT_IDE_LOAD = 60_000
TIMEOUT_SESSION_START = 90_000

# ---------------------------------------------------------------------------

# Keywords indicating the URL is a login/auth page (used for OIDC detection)
_LOGIN_KEYWORDS = ("sign-in", "login", "auth")


def _on_login_page(url: str) -> bool:
    """Return True if *url* looks like a login or IdP page."""
    lower = url.lower()
    return any(kw in lower for kw in _LOGIN_KEYWORDS)


def assert_homepage_loaded(page: Page) -> None:
    """Assert that the Workbench homepage has fully loaded.

    Verifies the Posit logo and new-session button are both visible.
    Use .first for NEW_SESSION_BUTTON as there can be two instances.
    """
    expect(page.locator(Homepage.POSIT_LOGO)).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)
    expect(page.locator(Homepage.NEW_SESSION_BUTTON).first).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)


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
    - Handles OIDC/SSO via pre-loaded storage state (--interactive-auth / --headless-auth)
    - Only fills login form for password auth
    - Retries on transient server errors (e.g., too many logins)

    Args:
        page: Playwright page object
        workbench_url: Base URL for Workbench (e.g., http://localhost:8787)
        username: Login username
        password: Login password
        auth_provider: Auth type (e.g., "password", "oidc", "saml")
        interactive_auth: True when an auth session is pre-loaded (either
            --interactive-auth or --headless-auth)
        max_retries: Max login attempts on transient errors (default 3)
        retry_delay: Seconds to wait between retries (default 2.0)

    Raises:
        pytest.skip: For non-password auth without a pre-loaded auth session,
            or when the session's storage state doesn't cover Workbench
        AssertionError: When password login fails after retries
    """
    homepage_logo = page.locator(Homepage.POSIT_LOGO)

    # For non-password auth without a pre-loaded auth session, skip immediately
    if auth_provider != "password" and not interactive_auth:
        pytest.skip(
            f"Login form not available for auth provider {auth_provider!r}. "
            "Pass --interactive-auth or --headless-auth to pre-load browser storage state."
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
            homepage_logo.wait_for(state="visible", timeout=TIMEOUT_QUICK)
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
            login_form.wait_for(state="visible", timeout=TIMEOUT_QUICK)
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
            homepage_or_error.wait_for(state="visible", timeout=TIMEOUT_PAGE_LOAD)
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
        # Use a temporary client so the session-scoped workbench_client's
        # cookie jar is never mutated.
        with httpx.Client(
            base_url=workbench_client.base_url,
            cookies=cookies,
            timeout=30.0,
        ) as tmp:
            resp = tmp.get("/api/sessions")
            sessions = resp.json() if resp.status_code == 200 else []
            for session in sessions:
                sid = session.get("id") or session.get("session_id", "")
                if not sid:
                    continue
                for method, path in (
                    ("DELETE", f"/api/sessions/{sid}"),
                    ("POST", f"/api/sessions/{sid}/suspend"),
                ):
                    try:
                        r = tmp.request(method, path)
                        if r.status_code < 400:
                            break
                    except Exception:
                        continue
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
    Handles password auth, OIDC via pre-loaded storage state (--interactive-auth /
    --headless-auth), and skips gracefully when auth type is unsupported.

    Returns the page for further interactions.
    """
    workbench_login(
        page, workbench_url, test_username, test_password, auth_provider, interactive_auth
    )

    assert_homepage_loaded(page)

    return page
