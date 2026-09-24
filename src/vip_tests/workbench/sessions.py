"""Session-state waits, failure and timeout messages, and unproven-skip helpers."""

from __future__ import annotations

import os
import time
from typing import NoReturn

from playwright.sync_api import Locator, Page, expect

from vip import attest
from vip_tests.workbench.pages import Homepage
from vip_tests.workbench.timeouts import (
    _SESSION_POLL_INTERVAL,
    TERMINAL_SESSION_FAILURE_STATES,
    TIMEOUT_CLEANUP,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_SESSION_START,
)


def _skip_workbench_session_unproven(
    *,
    auth_mode: str,
    workbench_auth_error: str | None,
    landed_url: str,
    idp_host: str | None = None,
) -> NoReturn:
    """Skip because a configured Workbench session could never be established.

    This is #596's case: the operator asked for Workbench explicitly, auth did
    not complete, and every browser test fell away. Reporting that as an
    ordinary skip is what let a fully unverified product exit 0, so it is
    raised as *unproven* -- the run stays green only under --allow-unproven.

    Contrast the ``sso_only`` skip further down ``_workbench_login``, which
    stays an ordinary skip on purpose: an SSO deployment genuinely has no
    password form to exercise, so that check is not applicable rather than
    unverified, and flagging it would fail every SSO deployment's own run.
    """
    attest.unproven(
        _workbench_session_skip_message(
            auth_mode=auth_mode,
            workbench_auth_error=workbench_auth_error,
            landed_url=landed_url,
            idp_host=idp_host,
        )
    )


def _workbench_session_skip_message(
    *,
    auth_mode: str,
    workbench_auth_error: str | None,
    landed_url: str,
    idp_host: str | None = None,
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

    *idp_host* names the identity provider when the deployment redirected
    sign-in off the Workbench origin entirely, so the reader knows the session
    expired at the IdP rather than looking for a Workbench sign-in page that
    was never rendered.
    """
    if auth_mode == "headless":
        flag = "--headless-auth"
    elif auth_mode == "interactive":
        flag = "--interactive-auth"
    else:
        flag = "--interactive-auth / --headless-auth"
    where = f"redirected to the {idp_host} sign-in page" if idp_host else "landed on login page"
    lines = [f"Workbench session not established by {flag} ({where}: {landed_url})."]
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
