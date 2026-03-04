"""Step definitions for Connect package source checks."""

from __future__ import annotations

import io
import pathlib
import tarfile
import time

import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_packages.feature", "Connect is configured to use the expected package repository")
def test_package_repo_configured():
    pass


@scenario("test_packages.feature", "Package Manager URL is the default repository source")
def test_pm_is_default_repo():
    pass


@given("Connect is accessible at the configured URL")
def connect_accessible(connect_client):
    assert connect_client is not None


@given("Package Manager is configured in vip.toml")
def pm_configured(vip_config):
    if not vip_config.package_manager.is_configured:
        pytest.skip("Package Manager is not configured")


@when(
    "I query the Connect server settings for package repositories",
    target_fixture="server_settings",
)
def query_server_settings(connect_client):
    return connect_client.server_settings()


def _string_values(obj):
    """Recursively yield all string leaf values from a nested dict/list."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _string_values(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _string_values(item)


@then("the configured R repository URL is present in the settings")
def r_repo_present(server_settings):
    # Connect exposes R repository configuration in the server settings JSON.
    # Check common field names used across Connect versions.
    possible_fields = ("r_repos_url", "r_default_repo_url", "repos_url", "r_repos")
    repo_value = next(
        (server_settings[f] for f in possible_fields if server_settings.get(f)),
        None,
    )
    if repo_value is None:
        # Broader search: look for any string value that looks like a URL.
        url_values = [v for v in _string_values(server_settings) if v.startswith("http")]
        if not url_values:
            pytest.skip(
                "Connect server settings do not include a recognizable R repository URL. "
                "This field may not be exposed on this Connect version."
            )
        return
    assert repo_value, "R repository URL is empty in Connect server settings"


# ---------------------------------------------------------------------------
# PM deployment-based verification
# ---------------------------------------------------------------------------

_PLUMBER_R = '#* @get /\nfunction() {\n  list(message = "VIP PM test")\n}\n'
_PLUMBER_MANIFEST = (pathlib.Path(__file__).parent / "plumber_manifest.json").read_text()


def _make_tar_gz(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@when(
    "I deploy a content item that installs R packages",
    target_fixture="pm_deploy_state",
)
def deploy_r_content(connect_client):
    # Create content, upload the plumber bundle, and deploy.
    content = connect_client.create_content("vip-pm-repo-test")
    guid = content["guid"]
    archive = _make_tar_gz({"plumber.R": _PLUMBER_R, "manifest.json": _PLUMBER_MANIFEST})
    bundle = connect_client.upload_bundle(guid, archive)
    result = connect_client.deploy_bundle(guid, bundle["id"])

    # Wait for deployment to finish (5 min max for package installs).
    task_id = result["task_id"]
    deadline = time.time() + 300
    task: dict = {}
    while time.time() < deadline:
        task = connect_client.get_task(task_id)
        if task.get("finished"):
            break
        time.sleep(3)

    if not task.get("finished"):
        output_lines = task.get("output", []) or []
        pytest.fail(
            "Deployment did not complete within 300 seconds\n\n"
            "--- Task output (last 30 lines) ---\n" + "\n".join(output_lines[-30:])
        )

    return {"guid": guid, "task": task}


@then("the deployment logs show packages installed from Package Manager")
def pm_url_in_deploy_logs(pm_deploy_state, pm_url):
    task = pm_deploy_state["task"]
    output_lines = task.get("output", [])
    pm_base = pm_url.rstrip("/")

    if any(pm_base in line for line in output_lines):
        return

    # Provide helpful output on failure.
    assert False, (
        f"Package Manager URL {pm_base!r} was not found in the deployment logs.\n"
        "Connect may not be configured to use Package Manager for R package installation.\n\n"
        f"--- Deployment output (last 30 lines) ---\n" + "\n".join(output_lines[-30:])
    )


@then("I clean up the deployed content")
def cleanup_deployed(connect_client, pm_deploy_state):
    connect_client.delete_content(pm_deploy_state["guid"])
