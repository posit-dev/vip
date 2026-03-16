"""Step definitions for cross-product integration tests."""

from __future__ import annotations

import pathlib

import pytest
from pytest_bdd import scenario, then, when

from tests.connect.conftest import _make_tar_gz


@scenario(
    "test_integration.feature",
    "Content deployed on Connect uses packages from Package Manager",
)
def test_connect_uses_package_manager():
    pass


# ---------------------------------------------------------------------------
# Bundle assets
# ---------------------------------------------------------------------------

_PLUMBER_R = '#* @get /\nfunction() {\n  list(message = "VIP integration test")\n}\n'
_PLUMBER_MANIFEST = (
    pathlib.Path(__file__).parent.parent / "connect" / "plumber_manifest.json"
).read_text()


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@when(
    "I deploy a content item that installs R packages on Connect",
    target_fixture="integration_deploy_state",
)
def deploy_r_content_on_connect(connect_client):
    content = connect_client.create_content("vip-integration-test")
    guid = content["guid"]
    archive = _make_tar_gz({"plumber.R": _PLUMBER_R, "manifest.json": _PLUMBER_MANIFEST})
    bundle = connect_client.upload_bundle(guid, archive)
    result = connect_client.deploy_bundle(guid, bundle["id"])

    task_id = result["task_id"]
    task = connect_client.wait_for_task(task_id, timeout=300)

    if not task.get("finished"):
        output_lines = task.get("output", []) or []
        pytest.fail(
            "Deployment did not complete within 300 seconds\n\n"
            "--- Task output (last 30 lines) ---\n" + "\n".join(output_lines[-30:])
        )

    return {"guid": guid, "task": task}


@then("the deployment logs mention the Package Manager URL as the package source")
def pm_url_in_integration_deploy_logs(integration_deploy_state, pm_url):
    task = integration_deploy_state["task"]
    output_lines = task.get("output", [])
    pm_base = pm_url.rstrip("/")

    if any(pm_base in line for line in output_lines):
        return

    assert False, (
        f"Package Manager URL {pm_base!r} was not found in the deployment logs.\n"
        "Connect may not be configured to use Package Manager for R package installation.\n\n"
        "--- Deployment output (last 30 lines) ---\n" + "\n".join(output_lines[-30:])
    )


@then("I clean up the integration test content")
def cleanup_integration_content(connect_client, integration_deploy_state):
    connect_client.delete_content(integration_deploy_state["guid"])
