"""Workbench-specific fixtures and helpers.

Page selectors are in the pages/ subpackage
"""

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

import pytest
from filelock import FileLock, Timeout
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from pytest_bdd import given

from vip.clients.workbench import WorkbenchClient
from vip.plugin import _auth_session_key
from vip.timeouts import timeout_scale
from vip.workbench_ui import (
    quit_vip_sessions_via_ui as _quit_vip_sessions_via_ui,
)

# Re-exported for selftests/test_workbench_cleanup.py, which imports it from
# here (not from vip.workbench_ui directly) to match the pre-move layout.
from vip.workbench_ui import (
    vip_names_from_select_labels as _vip_names_from_select_labels,  # noqa: F401
)
from vip_tests.workbench.pages import Homepage, LoginPage

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


pytestmark = [pytest.mark.workbench, pytest.mark.xdist_group("workbench")]


_IDE_MARKERS = ("rstudio", "vscode", "jupyter", "positron")


def _workbench_group_name(ide_markers: set[str], module_stem: str) -> str:
    """Compute the xdist group for a Workbench test under shared auth (hybrid grouping).

    IDE-launch scenarios (carrying an IDE marker) group by IDE so each IDE runs on its own
    worker: ``workbench_ide_<ide>``. Every other Workbench test groups by feature module:
    ``workbench_<stem>`` (a leading ``test_`` stripped).
    """
    for ide in _IDE_MARKERS:
        if ide in ide_markers:
            return f"workbench_ide_{ide}"
    stem = module_stem[len("test_") :] if module_stem.startswith("test_") else module_stem
    return f"workbench_{stem}"


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Group Workbench tests for parallel execution when a shared auth session is active.

    Under --interactive-auth / --headless-auth all Workbench tests authenticate as the same
    shared account. Rather than pin them all to one worker (the old serial workaround), we
    group them so LoadGroupScheduling spreads them across workers: IDE-launch scenarios by
    IDE (``workbench_ide_<ide>``), everything else by feature module (``workbench_<module>``).
    The simultaneous-login storm this used to cause is prevented by the cross-worker login
    lock in :func:`workbench_login` (see :func:`oidc_login_lock`), not by serialization.

    Password / no-auth runs are left untouched: they hit the early return below, so their
    Workbench items keep the default ``workbench`` group that ``plugin.py``'s
    :func:`_assign_xdist_group` directory fallback assigns (the module-level ``pytestmark``
    at the top of this file does not propagate to sibling test modules, so it assigns
    nothing here).
    """
    if config.stash.get(_auth_session_key, None) is None:
        # No shared auth session — password auth or no auth. Keep default parallel behavior.
        return

    workbench_dir = Path(__file__).parent
    for item in items:
        item_path = getattr(item, "path", None)
        if item_path is None or not item_path.is_relative_to(workbench_dir):
            continue
        ide_markers = {m.name for m in item.iter_markers()} & set(_IDE_MARKERS)
        group = _workbench_group_name(ide_markers, item_path.stem)
        # Strip any pre-existing xdist_group marker before adding the hybrid group. No
        # per-test xdist_group marker exists today, so this is a defensive guard: xdist
        # concatenates *all* xdist_group marks on an item (via iter_markers), it does not
        # take the closest, so a leftover mark would corrupt the group name rather than be
        # shadowed. plugin.py's _assign_xdist_group then respects the group we add here.
        item.own_markers = [m for m in item.own_markers if m.name != "xdist_group"]
        item.add_marker(pytest.mark.xdist_group(group))


# ---------------------------------------------------------------------------
# Playwright timeout constants (milliseconds)
# Scaled at definition time so all 9 importing step files pick up the scale
# without any call-site changes.  Set VIP_TIMEOUT_SCALE=N before running.
# ---------------------------------------------------------------------------

TIMEOUT_QUICK = int(5_000 * timeout_scale())
TIMEOUT_DIALOG = int(10_000 * timeout_scale())
TIMEOUT_PAGE_LOAD = int(15_000 * timeout_scale())
TIMEOUT_CLEANUP = int(30_000 * timeout_scale())
TIMEOUT_CODE_EXEC = int(30_000 * timeout_scale())
TIMEOUT_IDE_LOAD = int(60_000 * timeout_scale())
TIMEOUT_SESSION_START = int(90_000 * timeout_scale())
# Short window to detect whether an optional confirm/force-quit dialog appeared
# in the UI session sweep. Used to gate (not to click) so an absent dialog does
# not cost TIMEOUT_QUICK each iteration; a dialog that does appear is then
# clicked with the normal TIMEOUT_QUICK.
TIMEOUT_DIALOG_PROBE = int(1_000 * timeout_scale())

# Poll interval (ms) used while waiting for a session to reach Active.
_SESSION_POLL_INTERVAL = 500

# Session statuses that are terminal failures: the session has stopped and
# will never reach Active, so continuing to wait is pointless.  Detecting one
# of these lets the session-start wait fail fast with an actionable message
# instead of timing out on an opaque "Locator expected to be visible" error.
TERMINAL_SESSION_FAILURE_STATES = ("Failed",)

# ---------------------------------------------------------------------------
# Resource profile helpers
# Shared between test_session_capacity.py and test_session_capacity_k8s.py,
# both of which need to detect and skip resource profiles that Workbench
# renders as visible-but-disabled for the authenticated user.
# ---------------------------------------------------------------------------


class ResourceProfileDisabled(Exception):
    """Raised when the target resource profile is present but disabled for the user.

    Workbench renders resource profiles the authenticated user is not entitled
    to (e.g. a group-restricted profile) as visible options with
    ``aria-disabled='true'`` / ``data-disabled``.  Clicking one just blocks
    until Playwright's timeout, so ``_launch_session`` raises this instead and
    lets the caller record the profile as unavailable and move on.
    """

    def __init__(self, profile: str) -> None:
        super().__init__(profile)
        self.profile = profile


def _option_is_disabled(option: Locator) -> bool:
    """Return True if a ``[role='option']`` is disabled for the current user.

    Radix-based selects mark unavailable options with ``aria-disabled='true'``
    and an (empty-valued) ``data-disabled`` attribute; ``get_attribute``
    returns ``""`` for the latter, so test for presence rather than truthiness.
    """
    return (
        option.get_attribute("aria-disabled") == "true"
        or option.get_attribute("data-disabled") is not None
    )


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


def _session_failure_message(name: str, state: str, *, expected: str = "Active") -> str:
    """Build the error shown when a session reaches a terminal failure state.

    Replaces the opaque "Locator expected to be visible" timeout with a
    message that names the session, the terminal state observed, the state
    that was *expected*, and the likely cause — so the reader knows the
    deployment (not the test) could not reach the expected state.

    ``expected`` defaults to ``"Active"`` (the launch path).  For other
    targets (e.g. ``"Suspended"``) the cause is phrased as an abnormal exit
    rather than a failed launch, since the session did start before exiting.
    """
    if expected == "Active":
        cause = (
            "Workbench could not launch the session (abnormal exit). Verify the "
            "deployment can launch sessions: check the launcher, the session image, "
            "and available CPU/memory/quota."
        )
    else:
        cause = (
            "the session abnormally exited before reaching that state. Verify the "
            "deployment can suspend and resume sessions, and has available "
            "CPU/memory/quota."
        )
    return f"Session {name!r} reached terminal state {state!r} instead of {expected} — {cause}"


def _session_timeout_message(
    session_name: str, target_state: str, timeout_s: int, worker_count: int
) -> str:
    """Build the message shown when a session never reaches *target_state* before timeout.

    When running across multiple xdist workers (*worker_count* > 1), several sessions
    launch at once; a capacity-limited deployment can leave some stuck in a non-terminal
    "Starting" state. In that case, append a hint pointing at concurrent-session capacity
    so the failure is actionable rather than opaque.
    """
    base = (
        f"Session {session_name!r} did not reach {target_state} within {timeout_s}s "
        f"(no {target_state} or terminal status detected)."
    )
    if worker_count > 1:
        base += (
            f" This run used {worker_count} parallel workers, so multiple sessions were "
            "launching at once; if the deployment has limited concurrent-session capacity, "
            "sessions can stay in 'Starting' until they time out. Try reducing parallelism "
            "(e.g. a lower pytest -n) or verify the deployment/launcher can start that many "
            "sessions concurrently."
        )
    return base


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


def _visible_terminal_state(page: Page, session_name: str, *, target_state: str) -> str | None:
    """Return the terminal failure state currently shown for *session_name*, or None.

    Checks each state in :data:`TERMINAL_SESSION_FAILURE_STATES` (skipping
    *target_state*, the state we are waiting to reach) and returns the first
    whose status badge is visible.
    """
    for state in TERMINAL_SESSION_FAILURE_STATES:
        if state == target_state:
            continue
        loc = page.locator(Homepage.session_row_status(session_name, state))
        if loc.count() > 0 and loc.first.is_visible():
            return state
    return None


def raise_if_session_failed(page: Page, session_name: str, *, expected: str) -> None:
    """Fail fast if *session_name* is currently in a terminal failure state.

    Raises ``AssertionError`` with an actionable message (naming the terminal
    state observed and the *expected* state) when a session has abnormally
    exited, so waiters and reload loops surface a clear cause instead of
    waiting out their budget and emitting an opaque
    "Locator expected to be visible" error.  No-op otherwise.
    """
    failed_state = _visible_terminal_state(page, session_name, target_state=expected)
    if failed_state is not None:
        raise AssertionError(
            _session_failure_message(session_name, failed_state, expected=expected)
        )


def _wait_for_session_state(
    page: Page, session_name: str, target_state: str, *, timeout: int
) -> Locator:
    """Wait until *session_name* reaches *target_state*, failing fast on terminal states.

    Polls the session row for ``target_state``.  If the session instead
    reaches a terminal failure state (see :data:`TERMINAL_SESSION_FAILURE_STATES`),
    raises ``AssertionError`` immediately with an actionable message rather
    than waiting out the full ``timeout`` and emitting an opaque
    "Locator expected to be visible" error.

    Returns the session row locator so callers can chain further actions.
    """
    row = page.locator(Homepage.session_row(session_name))
    expect(row).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)

    target = page.locator(Homepage.session_row_status(session_name, target_state))

    def _target_now() -> bool:
        return target.count() > 0 and target.first.is_visible()

    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        if _target_now():
            return row
        raise_if_session_failed(page, session_name, expected=target_state)
        page.wait_for_timeout(_SESSION_POLL_INTERVAL)

    # Final check — the status may have flipped in the last poll interval.
    if _target_now():
        return row
    raise_if_session_failed(page, session_name, expected=target_state)
    worker_count = int(os.environ.get("PYTEST_XDIST_WORKER_COUNT", "1") or "1")
    raise AssertionError(
        _session_timeout_message(session_name, target_state, timeout // 1000, worker_count)
    )


def wait_for_session_active(
    page: Page, session_name: str, *, timeout: int = TIMEOUT_SESSION_START
) -> Locator:
    """Wait until *session_name* reaches Active, failing fast on terminal states.

    Returns the session row locator so callers can chain further actions
    (e.g. clicking the session's join link).
    """
    return _wait_for_session_state(page, session_name, "Active", timeout=timeout)


def wait_for_session_suspended(
    page: Page, session_name: str, *, timeout: int = TIMEOUT_CLEANUP
) -> Locator:
    """Wait until *session_name* reaches Suspended, failing fast on terminal states.

    The suspend counterpart to :func:`wait_for_session_active`.  If the session
    abnormally exits (terminal "Failed") instead of suspending, raises
    ``AssertionError`` immediately with an actionable message naming the
    abnormal exit, rather than waiting out ``timeout`` and emitting an opaque
    "Locator expected to be visible" error.
    """
    return _wait_for_session_state(page, session_name, "Suspended", timeout=timeout)


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
            homepage_logo.wait_for(state="visible", timeout=TIMEOUT_PAGE_LOAD)
            return True
        except (PlaywrightTimeoutError, PlaywrightError):
            # Homepage never appeared: no usable IdP session (expired, or storage state
            # stripped for the password-login test). Anything else (crashed page/context,
            # a bug in this helper) is a real failure and must propagate, not masquerade
            # as a graceful skip — matches the typed-catch convention used across this package.
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

    # Check if we landed on a login/IdP page
    if _on_login_page(page.url):
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
        except Exception:
            pass

        # An OIDC sign-in page shows a "Sign in with ..." button and no username
        # field. The "sign in" role-name also matches a password form's submit
        # button, so the *absence* of the username field is what distinguishes a
        # true SSO-only page from a password form.
        sso_button = page.get_by_role("button", name=re.compile(r"sign in", re.IGNORECASE)).first
        sso_only = sso_button.is_visible() and not page.locator(LoginPage.USERNAME).is_visible()

        if interactive_auth and sso_only:
            # Storage state was pre-loaded by --interactive-auth / --headless-auth.
            # Workbench's SSO sign-in page does not auto-redirect to the IdP; it renders a
            # "Sign in with OpenID" button. Clicking it triggers a silent SSO round-trip
            # using the saved IdP cookies. The round-trip is serialized across xdist
            # workers (see _silent_sso_signin / oidc_login_lock) to avoid storming the
            # shared IdP session (#484/#467).
            if _silent_sso_signin(sso_button, homepage_logo, workbench_url):
                return  # Silent SSO succeeded
            # No usable IdP session (expired, or storage state was stripped for the
            # password-login test) — skip gracefully.
            pytest.skip(
                _workbench_session_skip_message(
                    auth_mode=auth_mode,
                    workbench_auth_error=workbench_auth_error,
                    landed_url=page.url,
                )
            )

        if auth_provider != "password":
            pytest.skip(
                _workbench_session_skip_message(
                    auth_mode=auth_mode,
                    workbench_auth_error=workbench_auth_error,
                    landed_url=page.url,
                )
            )
        # Even when auth_provider is reported as "password", the deployment may
        # actually present an SSO/OIDC sign-in page (a "Sign in with ..." button
        # and no username field) — e.g. auth_provider defaulted to "password" on
        # a config-less run against an OIDC deployment.  The password login form
        # is unavailable there, so skip rather than fail the retry loop.
        if sso_only:
            pytest.skip(
                "Workbench is configured for SSO/OIDC (no password login form); "
                "the password-login scenario does not apply. Pass --interactive-auth "
                "or --headless-auth to exercise authenticated Workbench tests."
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


def _session_api_reachable_via_cookies(
    base_url: str,
    cookies: dict[str, str],
    *,
    insecure: bool,
    ca_bundle,
) -> bool:
    """Whether the session API is reachable for a cookie-authenticated client.

    Mirrors :func:`_quit_vip_sessions_via_cookies`: uses a scratch
    ``WorkbenchClient`` so the session-scoped client's cookie jar is untouched.
    Returns ``False`` on any error.
    """
    try:
        scratch = WorkbenchClient(base_url, insecure=insecure, ca_bundle=ca_bundle)
        try:
            scratch.set_cookies(cookies)
            return scratch.sessions_api_reachable()
        finally:
            scratch.close()
    except Exception:
        return False


def _vip_session_count_via_cookies(
    base_url: str,
    cookies: dict[str, str],
    *,
    insecure: bool,
    ca_bundle,
) -> int:
    """Count VIP-named sessions still listed for a cookie-authenticated client.

    Mirrors :func:`_quit_vip_sessions_via_cookies` / :func:`_session_api_reachable_via_cookies`:
    uses a scratch ``WorkbenchClient`` so the session-scoped client's cookie
    jar is untouched.  Convention: returns ``0`` only when the list call
    genuinely succeeded and no VIP sessions were found; returns ``-1`` when
    the count could not be determined at all (transport error, non-200,
    unparseable body) so callers can tell "confirmed clean" apart from
    "unknown" and escalate defensively in the latter case.  Never raises.
    """
    try:
        scratch = WorkbenchClient(base_url, insecure=insecure, ca_bundle=ca_bundle)
        try:
            scratch.set_cookies(cookies)
            return scratch.count_vip_sessions()
        finally:
            scratch.close()
    except Exception:
        return -1


@pytest.fixture(scope="session", autouse=True)
def _wb_cleanup_state(vip_config, workbench_client):
    """End-of-run safety net: sweep any VIP sessions left behind.

    Holds the most recent authenticated cookies captured by the per-test
    ``_cleanup_sessions`` fixture.  On teardown (after the whole Workbench
    run) it does one final ``quit_vip_sessions`` sweep, catching sessions
    orphaned when a per-test cleanup failed outright (e.g. the page crashed).
    """
    state: dict[str, object] = {"cookies": None, "base_url": None, "api_reachable": None}
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


def _run_session_cleanup(page, workbench_client, vip_config, state: dict[str, object]) -> None:
    """Quit any VIP-named Workbench sessions created during the test.

    Factored out of the ``_cleanup_sessions`` fixture body so it can be unit
    tested directly (the fixture depends on ``page``/``workbench_client``/
    ``vip_config``/``_wb_cleanup_state``, which are awkward to construct in a
    selftest). Runs the cookie/API sweep first, then escalates to a
    browser-driven UI sweep (:func:`_quit_vip_sessions_via_ui`) whenever the
    session API is unreachable *or* VIP sessions remain after the API sweep --
    not only when the API is unreachable, since a deployment can accept the
    DELETE/suspend call without the session actually terminating (issue #467).
    Defensive throughout: every network/Playwright call is wrapped so cleanup
    never raises out of the fixture; failures are logged as warnings (cleanup
    is a safety net, not an assertion) rather than failing the test.
    """
    if workbench_client is None:
        return
    try:
        cookies = {c["name"]: c["value"] for c in page.context.cookies()}
    except Exception:
        cookies = {}
    if not cookies:
        if not vip_config.workbench.api_key:
            logger.warning(
                "could not authenticate to clean up Workbench sessions at %s "
                "(no browser cookies captured and no [workbench] api_key configured); "
                "orphaned VIP sessions may remain.",
                workbench_client.base_url,
            )
        return
    # Remember the latest good cookies for the end-of-run sweep.
    state["cookies"] = cookies
    state["base_url"] = workbench_client.base_url
    _quit_vip_sessions_via_cookies(
        workbench_client.base_url,
        cookies,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
    )
    # Detect API reachability once per session (cached on state).
    if state["api_reachable"] is None:
        state["api_reachable"] = _session_api_reachable_via_cookies(
            workbench_client.base_url,
            cookies,
            insecure=vip_config.insecure,
            ca_bundle=vip_config.ca_bundle,
        )
    api_reachable = bool(state["api_reachable"])
    # Escalate to the UI sweep both when the API is unreachable (the cookie/API
    # sweep above was necessarily a no-op) AND when the API is reachable but
    # left VIP sessions behind (a no-op DELETE/suspend -- the actual #467 bug).
    # -1 ("could not determine") is treated the same as "sessions remain":
    # when in doubt, escalate rather than silently trust an unconfirmed sweep.
    remaining = _vip_session_count_via_cookies(
        workbench_client.base_url,
        cookies,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
    )
    if not api_reachable or remaining != 0:
        _quit_vip_sessions_via_ui(page, workbench_client.base_url)
        # Best-effort post-escalation check, for logging only -- never blocks
        # or fails the test.
        still_remaining = _vip_session_count_via_cookies(
            workbench_client.base_url,
            cookies,
            insecure=vip_config.insecure,
            ca_bundle=vip_config.ca_bundle,
        )
        if still_remaining > 0:
            logger.warning(
                "%d VIP-named Workbench session(s) may still be running at %s "
                "after the UI cleanup escalation; manual cleanup may be required.",
                still_remaining,
                workbench_client.base_url,
            )


@pytest.fixture(autouse=True)
def _cleanup_sessions(page, workbench_client, vip_config, _wb_cleanup_state):
    """Quit any VIP-named Workbench sessions created during the test."""
    yield
    _run_session_cleanup(page, workbench_client, vip_config, _wb_cleanup_state)


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


# ---------------------------------------------------------------------------
# Shared BDD steps
# ---------------------------------------------------------------------------


@given("Workbench is accessible and I am logged in")
def workbench_accessible_and_logged_in(
    page: Page,
    workbench_url: str,
    test_username: str,
    test_password: str,
    auth_provider: str,
    interactive_auth: bool,
    auth_mode: str,
    workbench_auth_error: str | None,
):
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


# ---------------------------------------------------------------------------
# Bundle path fixtures
# ---------------------------------------------------------------------------

_PYTHON_SHINY_APP = '''\
"""Minimal Python Shiny VIP test application."""

from shiny import App, ui

app_ui = ui.page_fixed(
    ui.h1("VIP Python Shiny Test"),
    ui.p("Deployed by VIP from a Workbench session."),
)


def server(input, output, session):
    pass


app = App(app_ui, server)
'''


def _write_python_shiny_bundle(bundle_dir: Path) -> Path:
    """Write a minimal Python Shiny bundle (app.py + requirements.txt) into bundle_dir.

    Returns *bundle_dir* for convenience so callers can write::

        path = _write_python_shiny_bundle(some_dir)
    """
    (bundle_dir / "app.py").write_text(_PYTHON_SHINY_APP)
    (bundle_dir / "requirements.txt").write_text("shiny\n")
    return bundle_dir


@pytest.fixture(scope="session")
def python_shiny_bundle_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a session-scoped Python Shiny test bundle in a temp directory.

    Writes a minimal ``app.py`` and ``requirements.txt`` to a fresh temp
    directory and returns the path.  The bundle is suitable for
    ``rsconnect deploy shiny <path>``.  Using ``tmp_path_factory`` means the
    files are created at test-run time on the machine running VIP (which must
    be the Workbench server, or a host whose /tmp is reachable from the
    Workbench session terminal).
    """
    return _write_python_shiny_bundle(tmp_path_factory.mktemp("python_shiny_bundle"))
