"""Cookie-based Workbench session cleanup and the autouse cleanup fixtures."""

from __future__ import annotations

import logging
from typing import TypedDict

import pytest
from playwright.sync_api import Page

from vip.clients.workbench import WorkbenchClient
from vip.config import VIPConfig
from vip.workbench_ui import (
    quit_vip_sessions_via_ui as _quit_vip_sessions_via_ui,
)
from vip_tests.workbench.naming import current_worker_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared Fixtures
# ---------------------------------------------------------------------------


def _quit_vip_sessions_via_cookies(
    base_url: str,
    cookies: dict[str, str],
    *,
    insecure: bool,
    ca_bundle,
    proxy=None,
    owner: str | None = None,
) -> int:
    """Quit VIP-named sessions using a scratch cookie-authenticated client.

    A scratch ``WorkbenchClient`` is used so the session-scoped
    ``workbench_client`` fixture's cookie jar is never mutated.  TLS config
    (``--insecure`` / ``--ca-bundle``) is honoured via *insecure*/*ca_bundle*.
    *owner* scopes the sweep to one xdist worker's own sessions.
    """
    try:
        scratch = WorkbenchClient(base_url, insecure=insecure, ca_bundle=ca_bundle, proxy=proxy)
        try:
            scratch.set_cookies(cookies)
            return scratch.quit_vip_sessions(owner=owner)
        finally:
            scratch.close()
    except Exception:  # noqa: BLE001
        return 0


def _session_api_reachable_via_cookies(
    base_url: str,
    cookies: dict[str, str],
    *,
    insecure: bool,
    ca_bundle,
    proxy=None,
) -> bool:
    """Whether the session API is reachable for a cookie-authenticated client.

    Mirrors :func:`_quit_vip_sessions_via_cookies`: uses a scratch
    ``WorkbenchClient`` so the session-scoped client's cookie jar is untouched.
    Returns ``False`` on any error.
    """
    try:
        scratch = WorkbenchClient(base_url, insecure=insecure, ca_bundle=ca_bundle, proxy=proxy)
        try:
            scratch.set_cookies(cookies)
            return scratch.sessions_api_reachable()
        finally:
            scratch.close()
    except Exception:  # noqa: BLE001
        return False


def _vip_session_count_via_cookies(
    base_url: str,
    cookies: dict[str, str],
    *,
    insecure: bool,
    ca_bundle,
    proxy=None,
    owner: str | None = None,
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
        scratch = WorkbenchClient(base_url, insecure=insecure, ca_bundle=ca_bundle, proxy=proxy)
        try:
            scratch.set_cookies(cookies)
            return scratch.count_vip_sessions(owner=owner)
        finally:
            scratch.close()
    except Exception:  # noqa: BLE001
        return -1


class _WbCleanupState(TypedDict):
    """Mutable state ``_cleanup_sessions`` writes and ``_wb_cleanup_state``'s
    teardown reads: the most recent authenticated cookies, the Workbench base
    URL they belong to, and a cached API-reachability probe result.
    """

    cookies: dict[str, str] | None
    base_url: str | None
    api_reachable: bool | None


@pytest.fixture(scope="session", autouse=True)
def _wb_cleanup_state(vip_config: VIPConfig, workbench_client: WorkbenchClient | None):
    """End-of-run safety net: sweep any VIP sessions left behind.

    Holds the most recent authenticated cookies captured by the per-test
    ``_cleanup_sessions`` fixture.  On teardown (after the whole Workbench
    run) it does one final ``quit_vip_sessions`` sweep, catching sessions
    orphaned when a per-test cleanup failed outright (e.g. the page crashed).
    """
    state: _WbCleanupState = {"cookies": None, "base_url": None, "api_reachable": None}
    yield state
    if workbench_client is None:
        return
    # Still worker-scoped: under xdist each worker tears down at the end of its
    # *own* session, which can be while a sibling worker is mid-test.  A truly
    # global sweep belongs to `vip cleanup --workbench-url`, which runs when no
    # worker is left to disturb.
    owner = current_worker_id()
    cookies = state["cookies"]
    if cookies:
        _quit_vip_sessions_via_cookies(
            str(state["base_url"]),
            cookies,
            insecure=vip_config.insecure,
            ca_bundle=vip_config.ca_bundle,
            proxy=vip_config.proxy,
            owner=owner,
        )
    # Belt-and-suspenders: when an API key is configured, also sweep with it.
    # Run this even if cookies were captured, because cookies may have expired
    # during a long run (a cookie sweep would then quietly clean up nothing).
    # quit_vip_sessions is idempotent, so this is a no-op when nothing remains.
    if vip_config.workbench.api_key:
        try:
            workbench_client.quit_vip_sessions(owner=owner)
        except Exception:  # noqa: BLE001
            pass


def _run_session_cleanup(
    page: Page,
    workbench_client: WorkbenchClient | None,
    vip_config: VIPConfig,
    state: _WbCleanupState,
) -> None:
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
    except Exception:  # noqa: BLE001
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
    # Scope every sweep to this worker's own sessions.  A bare VIP-prefix match
    # here quits sessions a sibling xdist worker is still driving mid-test,
    # which shows up as a vanished session row, an "Abnormal exits" toast, or a
    # "Session status: Quit" banner inside a live IDE.
    owner = current_worker_id()
    _quit_vip_sessions_via_cookies(
        workbench_client.base_url,
        cookies,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
        proxy=vip_config.proxy,
        owner=owner,
    )
    # Detect API reachability once per session (cached on state).
    if state["api_reachable"] is None:
        state["api_reachable"] = _session_api_reachable_via_cookies(
            workbench_client.base_url,
            cookies,
            insecure=vip_config.insecure,
            ca_bundle=vip_config.ca_bundle,
            proxy=vip_config.proxy,
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
        proxy=vip_config.proxy,
        owner=owner,
    )
    if not api_reachable or remaining != 0:
        _quit_vip_sessions_via_ui(page, workbench_client.base_url, owner=owner)
        # Best-effort post-escalation check, for logging only -- never blocks
        # or fails the test.
        still_remaining = _vip_session_count_via_cookies(
            workbench_client.base_url,
            cookies,
            insecure=vip_config.insecure,
            ca_bundle=vip_config.ca_bundle,
            proxy=vip_config.proxy,
            owner=owner,
        )
        if still_remaining > 0:
            logger.warning(
                "%d VIP-named Workbench session(s) may still be running at %s "
                "after the UI cleanup escalation; manual cleanup may be required.",
                still_remaining,
                workbench_client.base_url,
            )


def quit_owned_sessions_via_page(
    page, workbench_base_url: str, *, insecure: bool, ca_bundle
) -> None:
    """Quit this worker's VIP sessions using the browser page's own cookies.

    Shared by the capacity scenarios, which name sessions outside
    :func:`unique_session_name` and so clean up outside the autouse
    ``_cleanup_sessions`` fixture.  Always worker-scoped (see
    :func:`~vip.clients.workbench.is_vip_session_for_owner`) so a sibling xdist
    worker's live capacity sessions are left alone.  TLS config is threaded
    through so cleanup works against self-signed / custom-CA deployments.

    Lives here rather than in a step module so it stays importable from
    selftests: importing a pytest-bdd module inside a test trips ``@scenario``'s
    frame inspection and fails under pytest-randomly.  Best-effort, never raises.
    """
    try:
        cookies = {c["name"]: c["value"] for c in page.context.cookies()}
    except Exception:  # noqa: BLE001
        return
    if not cookies:
        return
    _quit_vip_sessions_via_cookies(
        workbench_base_url,
        cookies,
        insecure=insecure,
        ca_bundle=ca_bundle,
        owner=current_worker_id(),
    )


@pytest.fixture(autouse=True)
def _cleanup_sessions(
    page: Page,
    workbench_client: WorkbenchClient | None,
    vip_config: VIPConfig,
    _wb_cleanup_state: _WbCleanupState,
):
    """Quit any VIP-named Workbench sessions created during the test."""
    yield
    _run_session_cleanup(page, workbench_client, vip_config, _wb_cleanup_state)
