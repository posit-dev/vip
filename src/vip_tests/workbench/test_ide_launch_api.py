"""Step definitions for Workbench IDE launch via the Admin API (--api-auth).

Under ``--api-auth`` with a Workbench **super-admin** token these scenarios run
the IDE-launch checks purely through the Workbench Admin API — no browser is
used. Each scenario launches an IDE on behalf of the test user, polls until the
session is ``running``, then stops it. This is the Workbench analog of the
Connect API-key path: valuable for SSO-fronted deployments where browser auth
is not scriptable but an admin can mint an API token.

Layer 2 only: these steps are thin and talk exclusively to ``WorkbenchClient``.
There is deliberately no ``page``/Playwright import anywhere in this module —
that is the "API-only interaction" guarantee.
"""

from __future__ import annotations

import httpx
import pytest
from pytest_bdd import given, parsers, scenario, then, when

from vip.clients.workbench import (
    WORKBENCH_IDE_VALUES,
    WorkbenchSessionError,
)
from vip.timeouts import scaled
from vip_tests.workbench.conftest import unique_session_name

pytestmark = pytest.mark.order(20)

_FILENAME = "test_ide_launch_api.py"


@pytest.mark.workbench
@pytest.mark.rstudio
@scenario("test_ide_launch_api.feature", "RStudio session launches via the API and becomes active")
def test_launch_rstudio_api():
    pass


@pytest.mark.workbench
@pytest.mark.vscode
@scenario("test_ide_launch_api.feature", "VS Code session launches via the API and becomes active")
def test_launch_vscode_api():
    pass


@pytest.mark.workbench
@pytest.mark.jupyter
@scenario(
    "test_ide_launch_api.feature",
    "JupyterLab session launches via the API and becomes active",
)
def test_launch_jupyter_api():
    pass


@pytest.mark.workbench
@pytest.mark.positron
@scenario("test_ide_launch_api.feature", "Positron session launches via the API and becomes active")
def test_launch_positron_api():
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _api_privilege_skip(code: int) -> str:
    """Build the actionable skip message for a 401/403 from the Admin API."""
    return (
        f"Workbench Admin API returned HTTP {code}. IDE-launch over the API requires a "
        "super-admin token (admin tokens cannot launch sessions) on an Enhanced/Advanced "
        "deployment with workbench-api-super-admin-enabled=1 in rserver.conf. Verify the "
        "token type and that VIP_WORKBENCH_API_KEY is a super-admin token."
    )


def _ide_unavailable(exc: httpx.HTTPStatusError) -> bool:
    """Return True if a 400 body signals the requested IDE is not available.

    An IDE that is simply not installed on the deployment should *skip*
    (mirrors the UI test's "IDE not available … skip"), whereas an
    unclassifiable 400 is a real bug and should fail. Reads the response body
    defensively — never raises.
    """
    try:
        body = exc.response.text.lower()
    except Exception:
        return False
    signals = ("unsupported", "unknown workbench", "not available", "no such workbench")
    return any(signal in body for signal in signals)


# ---------------------------------------------------------------------------
# Teardown safety net
# ---------------------------------------------------------------------------


@pytest.fixture
def wb_api_state(workbench_client):
    """Hold the launched session id across steps; stop it on teardown if it leaks.

    Best-effort: if a scenario errors before the "session is stopped" step, this
    finalizer force-quits any still-tracked session so it does not orphan. Never
    raises — mirrors ``session_context``'s finalizer in the UI launch test. The
    end-of-run ``_wb_cleanup_state`` sweep in conftest re-sweeps VIP-named
    sessions via the API key as a further backstop.
    """
    state: dict = {"client": None, "username": None, "session_id": None, "ide": None}
    yield state
    sid = state.get("session_id")
    client = state.get("client")
    if sid and client is not None:
        try:
            client.stop_session(sid, force_quit=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@given("a Workbench API token that can launch sessions", target_fixture="wb_api")
def wb_api_ready(workbench_client, vip_config, test_username, wb_api_state):
    """Guard: skip gracefully unless a launch-capable API token + user are present.

    Workbench API-auth is opt-in and tier-gated, so a missing token/user or an
    unreachable/unauthorized Admin API is a *skip* (not a fail) — the correct
    layer for the graceful degradation the request calls for.
    """
    if workbench_client is None:
        pytest.skip("Workbench is not configured")
    if not vip_config.workbench.api_key:
        pytest.skip(
            "Workbench API IDE-launch requires an API token. "
            "Set VIP_WORKBENCH_API_KEY to a super-admin token and run with --api-auth."
        )
    if not test_username:
        pytest.skip(
            "Workbench API launch-on-behalf requires a target user. "
            "Set VIP_TEST_USERNAME (or [auth] username) to the test account to launch as."
        )
    # Confirm the API is reachable and the token is accepted before any launch.
    try:
        workbench_client.get_version()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code in (401, 403):
            pytest.skip(_api_privilege_skip(code))
        raise
    except httpx.HTTPError as exc:
        pytest.skip(f"Workbench Admin API not reachable at {workbench_client.base_url}: {exc}")
    wb_api_state["client"] = workbench_client
    wb_api_state["username"] = test_username
    return wb_api_state


@when(parsers.parse('I launch the "{ide}" IDE for the test user via the API'))
def launch_ide(wb_api, ide):
    """Launch *ide* on behalf of the test user; skip on privilege/availability."""
    if ide not in WORKBENCH_IDE_VALUES:
        pytest.fail(f"Unknown IDE {ide!r}; expected one of {sorted(WORKBENCH_IDE_VALUES)}")
    name = unique_session_name(_FILENAME)  # "VIP ..." -> is_vip_session matches for cleanup
    try:
        result = wb_api["client"].launch_session(
            WORKBENCH_IDE_VALUES[ide], username=wb_api["username"], name=name
        )
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code in (401, 403):
            pytest.skip(_api_privilege_skip(code))
        if code == 400 and _ide_unavailable(exc):
            pytest.skip(f"{ide} is not available for launch on this Workbench deployment.")
        raise
    wb_api["session_id"] = result["id"]
    wb_api["ide"] = ide


@then("the session reaches the active state")
def session_active(wb_api, vip_config):
    """Poll until the launched session is running; a never-active session fails."""
    timeout = scaled(vip_config.workbench.job_timeout)
    try:
        wb_api["client"].wait_for_active(
            wb_api["session_id"], username=wb_api["username"], timeout=timeout
        )
    except WorkbenchSessionError as exc:
        # Deployment couldn't bring the session up — a real failure, not a skip.
        raise AssertionError(str(exc)) from exc


@then("the session is stopped via the API")
def session_stopped(wb_api):
    """Stop the session and clear the tracked id so the finalizer is a no-op."""
    sid = wb_api.get("session_id")
    if sid:
        wb_api["client"].stop_session(sid, force_quit=True)
        wb_api["session_id"] = None
