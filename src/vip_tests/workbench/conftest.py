"""Workbench-specific fixtures and helpers.

Page selectors are in the pages/ subpackage
"""

from __future__ import annotations

import os
import time

import pytest
from playwright.sync_api import Locator, Page, expect

from vip.clients.workbench import WorkbenchClient
from vip_tests.workbench.pages import Homepage, LoginPage

pytestmark = [pytest.mark.workbench, pytest.mark.xdist_group("workbench")]

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

# Poll interval (ms) used while waiting for a session to reach Active.
_SESSION_POLL_INTERVAL = 500

# Session statuses that are terminal failures: the session has stopped and
# will never reach Active, so continuing to wait is pointless.  Detecting one
# of these lets the session-start wait fail fast with an actionable message
# instead of timing out on an opaque "Locator expected to be visible" error.
TERMINAL_SESSION_FAILURE_STATES = ("Failed",)

# ---------------------------------------------------------------------------


def unique_session_name(filename: str) -> str:
    """Generate a Workbench session name unique across xdist workers.

    Session tests look up rows via aria-label locators. Using only
    ``int(time.time())`` collided across workers that entered the same
    second, producing strict-mode failures once locators were tightened
    to ends-with matches. Worker id + nanosecond timestamp guarantees
    uniqueness for any practical parallelism.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    return f"VIP {filename} - {worker}-{time.time_ns()}"


# Keywords indicating the URL is a login/auth page (used for OIDC detection)
_LOGIN_KEYWORDS = ("sign-in", "login", "auth")


def _on_login_page(url: str) -> bool:
    """Return True if *url* looks like a login or IdP page."""
    lower = url.lower()
    return any(kw in lower for kw in _LOGIN_KEYWORDS)


def _workbench_session_skip_message(
    *,
    auth_mode: str,
    workbench_auth_error: str | None,
    landed_url: str,
) -> str:
    """Build the skip text shown when storage state did not log Workbench in.

    Names the active auth mode's CLI flag, quotes any error captured by
    ``_authenticate_workbench`` during pre-test sign-in, and lists the
    next steps a user can take.  Prior versions said "Interactive auth
    storage state did not authenticate Workbench" regardless of which
    mode was active and without surfacing the underlying cause.

    When *auth_mode* is unknown (a caller forgot to thread the fixture
    through), the message names both ``--interactive-auth`` and
    ``--headless-auth`` so the reader isn't pointed at the wrong flag.
    """
    if auth_mode == "headless":
        flag = "--headless-auth"
    elif auth_mode == "interactive":
        flag = "--interactive-auth"
    else:
        flag = "--interactive-auth / --headless-auth"
    lines = [f"Workbench session not established by {flag} (landed on login page: {landed_url})."]
    if workbench_auth_error:
        lines.append(f"Pre-test auth reported: {workbench_auth_error}")
    lines.append(
        "Next steps: rerun with --vip-verbose to see the auth flow, "
        "confirm the OIDC provider issues a session valid for Workbench's domain, "
        "and check that the Workbench auth-sign-in page does not require interaction."
    )
    return " ".join(lines)


def assert_homepage_loaded(page: Page) -> None:
    """Assert that the Workbench homepage has fully loaded.

    Verifies the Posit logo and new-session button are both visible.
    Use .first for NEW_SESSION_BUTTON as there can be two instances.
    """
    expect(page.locator(Homepage.POSIT_LOGO)).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)
    expect(page.locator(Homepage.NEW_SESSION_BUTTON).first).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)


def _session_failure_message(name: str, state: str) -> str:
    """Build the error shown when a session reaches a terminal failure state.

    Replaces the opaque "Locator expected to be visible" timeout with a
    message that names the session, the terminal state observed, and the
    likely cause — so the reader knows the deployment (not the test) could
    not launch the session.
    """
    return (
        f"Session {name!r} reached terminal state {state!r} instead of Active — "
        "Workbench could not launch the session (abnormal exit). Verify the "
        "deployment can launch sessions: check the launcher, the session image, "
        "and available CPU/memory/quota."
    )


def format_capacity_failure(total: int, failures: list[str], reasons: list[str]) -> str:
    """Build the aggregated failure for the session-capacity scenario.

    Reports how many sessions reached Active and which profiles failed, then
    appends each per-session diagnostic captured from
    :func:`wait_for_session_active`.  Keeping the reasons means an aggregated
    capacity failure still names the terminal state (e.g. ``Failed``) and its
    likely cause, instead of collapsing to a bare profile list.
    """
    passed = total - len(failures)
    lines = [f"{passed}/{total} sessions reached Active. Failed profiles: {', '.join(failures)}"]
    lines.extend(reasons)
    return "\n".join(lines)


def wait_for_session_active(
    page: Page, session_name: str, *, timeout: int = TIMEOUT_SESSION_START
) -> Locator:
    """Wait until *session_name* reaches Active, failing fast on terminal states.

    Polls the session row for the Active status.  If the session instead
    reaches a terminal failure state (see :data:`TERMINAL_SESSION_FAILURE_STATES`),
    raises ``AssertionError`` immediately with an actionable message rather
    than waiting out the full ``timeout`` and emitting an opaque
    "Locator expected to be visible" error.

    Returns the session row locator so callers can chain further actions
    (e.g. clicking the session's join link).
    """
    row = page.locator(Homepage.session_row(session_name))
    expect(row).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)

    active = page.locator(Homepage.session_row_status(session_name, "Active"))
    terminal = {
        state: page.locator(Homepage.session_row_status(session_name, state))
        for state in TERMINAL_SESSION_FAILURE_STATES
    }

    def _active_now() -> bool:
        return active.count() > 0 and active.first.is_visible()

    def _terminal_now() -> str | None:
        for state, loc in terminal.items():
            if loc.count() > 0 and loc.first.is_visible():
                return state
        return None

    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        if _active_now():
            return row
        failed_state = _terminal_now()
        if failed_state is not None:
            raise AssertionError(_session_failure_message(session_name, failed_state))
        page.wait_for_timeout(_SESSION_POLL_INTERVAL)

    # Final check — the status may have flipped in the last poll interval.
    if _active_now():
        return row
    failed_state = _terminal_now()
    if failed_state is not None:
        raise AssertionError(_session_failure_message(session_name, failed_state))
    raise AssertionError(
        f"Session {session_name!r} did not reach Active within {timeout // 1000}s "
        "(no Active or terminal status detected)."
    )


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
    auth_mode: str = "none",
    workbench_auth_error: str | None = None,
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
        auth_mode: Active auth mode ("interactive", "headless", or "none"),
            used to name the responsible CLI flag in skip messages
        workbench_auth_error: Reason the pre-test auth flow could not
            establish a Workbench session, if known.  Quoted in the skip
            message so users see the real cause instead of a guess.
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
            pytest.skip(
                _workbench_session_skip_message(
                    auth_mode=auth_mode,
                    workbench_auth_error=workbench_auth_error,
                    landed_url=page.url,
                )
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


def _quit_vip_sessions_via_cookies(
    base_url: str,
    cookies: dict[str, str],
    *,
    insecure: bool,
    ca_bundle,
) -> int:
    """Quit VIP-named sessions using a scratch cookie-authenticated client.

    A scratch ``WorkbenchClient`` is used so the session-scoped
    ``workbench_client`` fixture's cookie jar is never mutated.  TLS config
    (``--insecure`` / ``--ca-bundle``) is honoured via *insecure*/*ca_bundle*.
    """
    try:
        scratch = WorkbenchClient(base_url, insecure=insecure, ca_bundle=ca_bundle)
        try:
            scratch.set_cookies(cookies)
            return scratch.quit_vip_sessions()
        finally:
            scratch.close()
    except Exception:
        return 0


@pytest.fixture(scope="session", autouse=True)
def _wb_cleanup_state(vip_config, workbench_client):
    """End-of-run safety net: sweep any VIP sessions left behind.

    Holds the most recent authenticated cookies captured by the per-test
    ``_cleanup_sessions`` fixture.  On teardown (after the whole Workbench
    run) it does one final ``quit_vip_sessions`` sweep, catching sessions
    orphaned when a per-test cleanup failed outright (e.g. the page crashed).
    """
    state: dict[str, object] = {"cookies": None, "base_url": None}
    yield state
    if workbench_client is None:
        return
    cookies = state["cookies"]
    if cookies:
        _quit_vip_sessions_via_cookies(
            str(state["base_url"]),
            cookies,  # type: ignore[arg-type]
            insecure=vip_config.insecure,
            ca_bundle=vip_config.ca_bundle,
        )
    # Belt-and-suspenders: when an API key is configured, also sweep with it.
    # Run this even if cookies were captured, because cookies may have expired
    # during a long run (a cookie sweep would then quietly clean up nothing).
    # quit_vip_sessions is idempotent, so this is a no-op when nothing remains.
    if vip_config.workbench.api_key:
        try:
            workbench_client.quit_vip_sessions()
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _cleanup_sessions(page, workbench_client, vip_config, _wb_cleanup_state):
    """Quit any VIP-named Workbench sessions created during the test."""
    yield
    if workbench_client is None:
        return
    try:
        cookies = {c["name"]: c["value"] for c in page.context.cookies()}
    except Exception:
        cookies = {}
    if not cookies:
        return
    # Remember the latest good cookies for the end-of-run sweep.
    _wb_cleanup_state["cookies"] = cookies
    _wb_cleanup_state["base_url"] = workbench_client.base_url
    _quit_vip_sessions_via_cookies(
        workbench_client.base_url,
        cookies,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
    )


@pytest.fixture
def wb_login(
    page: Page,
    workbench_url: str,
    test_username: str,
    test_password: str,
    auth_provider: str,
    interactive_auth: bool,
    auth_mode: str,
    workbench_auth_error: str | None,
):
    """Log in to Workbench and verify homepage loads.

    This fixture handles the complete login flow using rstudio-pro patterns.
    Handles password auth, OIDC via pre-loaded storage state (--interactive-auth /
    --headless-auth), and skips gracefully when auth type is unsupported.

    Returns the page for further interactions.
    """
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

    return page
