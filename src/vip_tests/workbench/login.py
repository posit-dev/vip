"""Workbench login: the cross-worker OIDC login lock, silent SSO, and ``workbench_login``."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import re
import tempfile
import time
import warnings
from pathlib import Path
from urllib.parse import urlparse

import pytest
from filelock import FileLock, Timeout
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from vip.auth import refresh_auth_cache_from_storage_state
from vip.auth.workbench import _on_login_page
from vip_tests.workbench.pages import Homepage, LoginPage
from vip_tests.workbench.sessions import _skip_workbench_session_unproven
from vip_tests.workbench.timeouts import TIMEOUT_PAGE_LOAD, TIMEOUT_QUICK, TIMEOUT_SSO_ROUNDTRIP

logger = logging.getLogger(__name__)

# Cross-worker OIDC login lock (#484). Under --interactive-auth / --headless-auth every
# xdist worker shares one IdP session; letting many workers do the silent SSO round-trip
# simultaneously storms the IdP (the ?error=2 bounce from #467). Serializing just the
# round-trip removes the concurrency without re-serializing the whole suite.
_LOGIN_LOCK_TIMEOUT = float(os.environ.get("VIP_LOGIN_LOCK_TIMEOUT", "60"))


def _login_lock_path(workbench_url: str) -> Path:
    """Path to the cross-worker OIDC login lock for *workbench_url*.

    Keyed by a hash of the URL so distinct deployments don't share a lock, and placed in
    the system temp dir so all xdist workers on the host share the same file.
    """
    digest = hashlib.sha256(workbench_url.encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"vip-wb-login-{digest}.lock"


@contextlib.contextmanager
def oidc_login_lock(workbench_url: str, *, timeout: float = _LOGIN_LOCK_TIMEOUT):
    """Serialize the OIDC SSO round-trip across xdist workers.

    Only one worker performs the silent SSO round-trip against the shared IdP session at a
    time. The lock is a best-effort optimization: falling back to unlocked proceeds
    correctly, though it can reintroduce the very login storm this lock exists to avoid. If
    it can't be acquired within *timeout*, surface a warning and proceed unlocked rather
    than hang the run.
    """
    lock = FileLock(str(_login_lock_path(workbench_url)))
    try:
        lock.acquire(timeout=timeout)
    except Timeout:
        # Emit via both channels: warnings.warn surfaces in pytest's warnings summary
        # regardless of pass/fail (no logging handler is attached for test runs), so the
        # one run where storm-prevention disengaged leaves a forensic trail for later.
        message = (
            f"OIDC login lock not acquired within {timeout:.0f}s for {workbench_url}; "
            "proceeding without it. Concurrent logins may briefly storm the IdP."
        )
        warnings.warn(message, stacklevel=2)
        logger.warning(message)
        yield
        return
    try:
        yield
    finally:
        lock.release()


# Keywords indicating the URL is a login/auth page (used for OIDC detection)
# Passed to vip.auth.workbench._on_login_page in place of its SAML-aware default.
_LOGIN_KEYWORDS = ("sign-in", "login", "auth")


def _navigated_into_session(url: str) -> bool:
    """Return True if *url* is inside a session, not the homepage.

    Workbench's homepage is itself served under a "/s/<id>/" URL (its
    "workspaces" view), so a bare "/s/" check can't tell the two apart. A
    real session URL has no "workspaces" segment after the id.
    """
    segments = [s for s in urlparse(url).path.split("/") if s]
    if len(segments) < 2 or segments[0] != "s":
        return False
    return "workspaces" not in segments


def _external_idp_host(page_url: str, workbench_url: str) -> str | None:
    """Return the IdP host if sign-in has left the Workbench origin.

    Some deployments do not render a Workbench sign-in page at all: an
    unauthenticated request redirects straight out to the identity provider
    (e.g. ``https://posit.okta.com/oauth2/v1/authorize?...``).  That page has
    neither Workbench's ``#username`` field nor a "Sign in with ..." button --
    Okta's identifier-first submit is named "Next" -- so button/field probing
    alone reads it as a password deployment and grinds the retry loop into
    "Login failed after 3 attempts".  Comparing the landed host against the
    configured Workbench host settles it without depending on any one IdP's
    markup.  Returns ``None`` when still on the Workbench origin (or when
    either URL cannot be parsed).
    """
    try:
        landed = urlparse(page_url)
        configured = urlparse(workbench_url)
    except ValueError:
        return None
    current = _normalised_netloc(landed)
    expected = _normalised_netloc(configured)
    if current and expected and current != expected:
        return landed.netloc
    return None


# Ports that carry no information because they are implied by the scheme.
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _normalised_netloc(parsed) -> str:
    """Return *parsed*'s host:port with a scheme-default port dropped, lowercased.

    ``https://wb.example.com`` and ``https://wb.example.com:443`` are the same
    origin, but their raw ``netloc`` strings differ.  Comparing raw values makes
    a Workbench URL configured with an explicit default port look like a
    redirect away from itself, which would skip every password-login scenario on
    a deployment that is not federated at all.
    """
    host = (parsed.hostname or "").lower()
    if not host:
        return ""
    try:
        port = parsed.port
    except ValueError:
        # A malformed port ("https://host:notaport") -- keep the raw form rather
        # than silently treating it as the default.
        return parsed.netloc.lower()
    if port is None or port == _DEFAULT_PORTS.get(parsed.scheme.lower()):
        return host
    return f"{host}:{port}"


# ---------------------------------------------------------------------------
# Login Helper
# ---------------------------------------------------------------------------


def _silent_sso_signin(sso_button, homepage_logo, workbench_url: str) -> bool:
    """Click the OIDC sign-in button and wait for the homepage, serialized across workers.

    Wrapped in :func:`oidc_login_lock` so concurrent xdist workers don't storm the shared
    IdP session. Returns ``True`` when the authenticated homepage appears, ``False``
    otherwise (the caller then skips with the standard message).
    """
    with oidc_login_lock(workbench_url):
        sso_button.click()
        try:
            homepage_logo.wait_for(state="visible", timeout=TIMEOUT_SSO_ROUNDTRIP)
            return True
        except (PlaywrightTimeoutError, PlaywrightError):
            # Homepage never appeared: no usable IdP session (expired, or storage state
            # stripped for the password-login test). Anything else (crashed page/context,
            # a bug in this helper) is a real failure and must propagate, not masquerade
            # as a graceful skip — matches the typed-catch convention used across this package.
            return False


def _refresh_cached_session(page: Page) -> bool:
    """Write this context's storage state back to the auth cache. Always True.

    The caller has already established that the session is live, so the return
    value reports *the restore*, not the cache write: a cache that could not be
    refreshed (absent, read-only) is a slower next run, not a failed restore,
    and must not be reported as one.
    """
    try:
        refresh_auth_cache_from_storage_state(dict(page.context.storage_state()))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not read storage state to refresh the auth cache: %s", exc)
    return True


def restore_shared_session(page: Page, workbench_url: str) -> bool:
    """Sign back in after the sign-out scenario, returning whether it worked.

    The scenario deliberately ends the session every other scenario shares, so
    it has to hand one back. Navigating to Workbench and completing the silent
    SSO round-trip mints a fresh session in this browser context.

    A successful restore also writes the fresh session back to the auth cache on
    disk. Without that the in-run damage is repaired but the cache still holds
    the cookies the sign-out killed, so the *next* ``vip verify`` rejects it and
    drops into an interactive re-auth -- a browser popup on every run.

    Returns False -- and warns -- when the round-trip cannot complete, e.g. the
    IdP applied single-logout and cleared its own cookies too. That is not
    something this fixture can repair, but it must be visible: silently leaving
    the suite signed out is how a sign-out turns into a cascade of unrelated
    auth failures in later scenarios.
    """
    logo = page.locator(Homepage.POSIT_LOGO)
    try:
        page.goto(workbench_url)
        page.wait_for_load_state("load")
        if logo.is_visible():
            return _refresh_cached_session(page)
        sso_button = page.get_by_role("button", name=re.compile(r"sign in", re.IGNORECASE)).first
        if sso_button.is_visible() and _silent_sso_signin(sso_button, logo, workbench_url):
            return _refresh_cached_session(page)
    except (PlaywrightTimeoutError, PlaywrightError) as exc:
        logger.warning("Could not sign back in after the sign-out scenario: %s", exc)
        return False
    logger.warning(
        "Could not sign back in after the sign-out scenario at %s: the silent SSO round-trip "
        "did not reach an authenticated homepage (the identity provider may have applied "
        "single-logout). Later scenarios and the cached auth session are now signed out; "
        "rerun with --interactive-auth to re-establish one.",
        workbench_url,
    )
    return False


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

    # A valid session cookie can redirect straight into a running session's IDE
    # view instead of the homepage -- that view has none of Homepage's chrome, so
    # the check above misses it and the login-page probe below also misses it
    # (it's neither a login page nor the homepage). Same case test_sessions.py
    # handles when navigating back from a session: go to /home explicitly.
    if "/s/" in page.url:
        page.goto(f"{workbench_url}/home")
        page.wait_for_load_state("load")
        if homepage_logo.is_visible():
            return

    # Check if we landed on a login/IdP page
    if _on_login_page(page.url, _LOGIN_KEYWORDS):
        # The sign-in page renders client-side after ``load``; wait once for
        # either the password form's username field or an OIDC "Sign in with ..."
        # button to appear before deciding which flow applies. A short fixed wait
        # on only the SSO button races the render and can misread a slow OIDC
        # sign-in page (e.g. an ``?error=2`` bounce) as a password deployment --
        # which then fails the retry loop with "Login failed after 3 attempts"
        # instead of skipping. Waiting for either control settles that race
        # without penalising real password deployments (the username field
        # appears promptly there).
        try:
            page.locator(f"{LoginPage.USERNAME}, button:has-text('Sign in')").first.wait_for(
                state="visible", timeout=TIMEOUT_PAGE_LOAD
            )
        except Exception:  # noqa: BLE001
            pass

        # An OIDC sign-in page shows a "Sign in with ..." button and no username
        # field. The "sign in" role-name also matches a password form's submit
        # button, so the *absence* of the username field is what distinguishes a
        # true SSO-only page from a password form.
        sso_button = page.get_by_role("button", name=re.compile(r"sign in", re.IGNORECASE)).first
        sso_button_present = sso_button.is_visible()
        # A deployment can also skip its own sign-in page entirely and redirect
        # straight to the IdP, whose markup matches neither probe above (see
        # _external_idp_host). Landing off the Workbench origin is conclusive on
        # its own: no Workbench password form is reachable from there.
        idp_host = _external_idp_host(page.url, workbench_url)
        sso_only = idp_host is not None or (
            sso_button_present and not page.locator(LoginPage.USERNAME).is_visible()
        )

        if interactive_auth and sso_only:
            # Storage state was pre-loaded by --interactive-auth / --headless-auth.
            # Workbench's SSO sign-in page does not auto-redirect to the IdP; it renders a
            # "Sign in with OpenID" button. Clicking it triggers a silent SSO round-trip
            # using the saved IdP cookies. The round-trip is serialized across xdist
            # workers (see _silent_sso_signin / oidc_login_lock) to avoid storming the
            # shared IdP session (#484/#467).  When the deployment redirected us
            # off-origin instead there is no such button to click, so go straight
            # to the skip -- clicking a locator that resolves to nothing would
            # raise a Playwright error in place of an actionable skip.
            if sso_button_present and _silent_sso_signin(sso_button, homepage_logo, workbench_url):
                return  # Silent SSO succeeded
            # No usable IdP session (expired, or storage state was stripped for the
            # password-login test) — skip gracefully.  Recompute the IdP host: the
            # click above can navigate off-origin before timing out, so where we
            # ended up is only knowable now, not before the attempt.
            _skip_workbench_session_unproven(
                auth_mode=auth_mode,
                workbench_auth_error=workbench_auth_error,
                landed_url=page.url,
                idp_host=_external_idp_host(page.url, workbench_url),
            )

        if auth_provider != "password":
            _skip_workbench_session_unproven(
                auth_mode=auth_mode,
                workbench_auth_error=workbench_auth_error,
                landed_url=page.url,
                idp_host=_external_idp_host(page.url, workbench_url),
            )
        # Even when auth_provider is reported as "password", the deployment may
        # actually present an SSO/OIDC sign-in page (a "Sign in with ..." button
        # and no username field) — e.g. auth_provider defaulted to "password" on
        # a config-less run against an OIDC deployment.  The password login form
        # is unavailable there, so skip rather than fail the retry loop.
        if sso_only:
            where = (
                f"redirects sign-in to the identity provider at {idp_host}"
                if idp_host
                else "presents an SSO/OIDC sign-in page instead (no username/password fields)"
            )
            pytest.skip(
                "This scenario requires a Workbench password-login form, but the "
                f"deployment {where}. Password login cannot be exercised on an SSO "
                "deployment, so this scenario is skipped."
            )
        # Password auth - proceed with form login below
    else:
        # Not on homepage, not on login page - unexpected state
        # Give it one more check in case page is still loading
        try:
            homepage_logo.wait_for(state="visible", timeout=TIMEOUT_QUICK)
            return
        except Exception:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001
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
        except Exception as exc:
            if attempt == max_retries - 1:
                raise AssertionError(
                    f"Login failed after {max_retries} attempts: no response"
                ) from exc
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
