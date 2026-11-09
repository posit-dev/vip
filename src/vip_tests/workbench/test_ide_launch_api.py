"""Step definitions for Workbench IDE launch through the Workbench API.

Under ``--api-auth`` there is no browser login, so these scenarios drive Workbench
with an API token alone: launch an IDE for the test user, wait until the session
is running, then stop it.  The token must be a super-admin token (or a user token
owned by the test user) on an Enhanced or Advanced deployment with the API enabled
in ``rserver.conf``.  Nothing here touches Playwright.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from vip import attest
from vip.clients.workbench import (
    WorkbenchApiError,
    WorkbenchClient,
    default_launch_parameters,
    is_ide_offered,
)
from vip_tests.workbench.conftest import TIMEOUT_SESSION_START, unique_session_name

pytestmark = pytest.mark.order(20)

_FILENAME = Path(__file__).name

# A 401 or 403 from the API is a rejected token; a 404 is an API that is switched off.
_API_REFUSED = (401, 403, 404)


@pytest.mark.rstudio
@scenario("test_ide_launch_api.feature", "RStudio session can be launched through the API")
def test_launch_rstudio_api():
    pass


@pytest.mark.vscode
@scenario("test_ide_launch_api.feature", "VS Code session can be launched through the API")
def test_launch_vscode_api():
    pass


@pytest.mark.jupyter
@scenario("test_ide_launch_api.feature", "JupyterLab session can be launched through the API")
def test_launch_jupyter_api():
    pass


@pytest.mark.positron
@scenario("test_ide_launch_api.feature", "Positron session can be launched through the API")
def test_launch_positron_api():
    pass


def _api_refused_message(exc: WorkbenchApiError) -> str:
    """Why a token that is configured could not be used, with the usual fixes."""
    return (
        f"The Workbench API refused the configured token ({exc}). Check that "
        "VIP_WORKBENCH_API_KEY is a super-admin token from `rstudio-server "
        "generate-api-token`, that rserver.conf sets workbench-api-enabled=1 and "
        "workbench-api-super-admin-enabled=1, and that the deployment is Enhanced or Advanced."
    )


@pytest.fixture
def wb_api_session():
    """Track the launched session so it is stopped even when a step fails."""
    state: dict[str, Any] = {"client": None, "id": None}
    yield state
    if state["client"] is not None and state["id"]:
        state["client"].stop_session(state["id"], force_quit=True)


@given("a Workbench API token that can launch sessions", target_fixture="wb_api")
def wb_api_ready(
    workbench_client: WorkbenchClient | None,
    vip_config,
    test_username: str,
    wb_api_session: dict[str, Any],
):
    if workbench_client is None:
        attest.not_applicable("Workbench is not configured.")
    if not vip_config.workbench.api_key:
        attest.not_applicable(
            "No Workbench API token is configured (VIP_WORKBENCH_API_KEY), so there is "
            "nothing to launch sessions with."
        )
    if not test_username:
        attest.not_applicable(
            "No test username is configured, so there is no user to launch sessions for."
        )
    try:
        workbench_client.get_version()
        compute_envs = workbench_client.get_compute_envs()
    except WorkbenchApiError as exc:
        if exc.status_code in _API_REFUSED:
            attest.unproven(_api_refused_message(exc))
        raise
    wb_api_session["client"] = workbench_client
    return {
        "client": workbench_client,
        "username": test_username,
        "compute_envs": compute_envs,
        "session": wb_api_session,
    }


@when(parsers.parse('I launch the "{ide}" IDE for the test user through the API'))
def launch_ide(wb_api: dict[str, Any], ide: str):
    if not is_ide_offered(wb_api["compute_envs"], ide):
        attest.not_applicable(f"{ide} is not offered by this Workbench deployment.")
    name = unique_session_name(_FILENAME)
    params = default_launch_parameters(wb_api["compute_envs"], ide, name)
    try:
        launched = wb_api["client"].launch_session(
            ide, username=wb_api["username"], name=name, launch_parameters=params
        )
    except WorkbenchApiError as exc:
        if exc.status_code in _API_REFUSED:
            attest.unproven(_api_refused_message(exc))
        raise
    wb_api["session_id"] = launched["id"]
    wb_api["session"]["id"] = launched["id"]


@then("the session reaches the running state")
def session_running(wb_api: dict[str, Any]):
    wb_api["client"].wait_for_session_running(
        wb_api["session_id"], user=wb_api["username"], timeout=TIMEOUT_SESSION_START / 1000
    )


@then("the session can be stopped through the API")
def session_stopped(wb_api: dict[str, Any]):
    stopped = wb_api["client"].stop_session(wb_api["session_id"], force_quit=True)
    assert stopped, f"Workbench API did not accept stop_session for {wb_api['session_id']}"
    wb_api["session"]["id"] = None
