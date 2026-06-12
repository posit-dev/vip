"""Step definitions for cross-product GxP validation example.

Demonstrates how to write a VIP test extension that:
- Verifies specific R/Python versions are available on Connect
- Verifies that key packages (jsonlite, PyDeSEQ2) are installable on Connect
- Verifies package installation in a live Workbench RStudio session

This file uses VIP's four-layer architecture:
  Layer 1: feature file (Gherkin)
  Layer 2: these step definitions + conftest fixtures
  Layer 3: ConnectClient / Playwright page from VIP core
  Layer 4: httpx (API) / Playwright (browser)

To run this extension:
  vip verify --config vip.toml --extensions /path/to/cross_product_validation
"""

from __future__ import annotations

import io
import json
import tarfile

import pytest
from pytest_bdd import given, scenario, then, when

from vip_tests.workbench.exec import terminal_run

# ---------------------------------------------------------------------------
# Scenarios — each carries explicit pytest markers for auto-skip
# ---------------------------------------------------------------------------


@pytest.mark.connect
@scenario("test_gxp_validation.feature", "Connect R versions match requirements")
def test_connect_r_versions():
    pass


@pytest.mark.connect
@scenario("test_gxp_validation.feature", "Connect Python versions match requirements")
def test_connect_python_versions():
    pass


@pytest.mark.connect
@scenario("test_gxp_validation.feature", "R package is installable on Connect")
def test_connect_r_package():
    pass


@pytest.mark.connect
@scenario("test_gxp_validation.feature", "Python package is installable on Connect")
def test_connect_python_package():
    pass


@pytest.mark.workbench
@scenario(
    "test_gxp_validation.feature",
    "R package is installable in Workbench RStudio session",
)
def test_workbench_r_package():
    pass


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------


@given("Connect is accessible at the configured URL")
def connect_accessible(connect_client):
    assert connect_client is not None, "Connect client not configured"
    status = connect_client.health()
    assert status < 400, f"Connect returned HTTP {status}"


@given("expected R versions are specified in vip.toml")
def r_versions_specified(expected_r_versions):
    if not expected_r_versions:
        pytest.skip("No expected R versions specified in vip.toml [runtimes]")


@given("expected Python versions are specified in vip.toml")
def python_versions_specified(expected_python_versions):
    if not expected_python_versions:
        pytest.skip("No expected Python versions specified in vip.toml [runtimes]")


@given("package install checks are enabled")
def package_checks_enabled(check_packages):
    if not check_packages:
        pytest.skip("Package install checks skipped (check_packages=False in conftest.py)")


@given("a Workbench RStudio session is open")
def workbench_session_open(page):
    # The `page` fixture is provided by VIP core when Workbench is configured.
    assert page is not None, "Workbench browser session not available"


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when("I query Connect for available R versions", target_fixture="available_r")
def query_r_versions(connect_client):
    return connect_client.r_versions()


@when("I query Connect for available Python versions", target_fixture="available_python")
def query_python_versions(connect_client):
    return connect_client.python_versions()


def _make_tar_gz(files: dict[str, str]) -> bytes:
    """Create an in-memory tar.gz archive from a dict of {filename: content}."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _r_package_manifest(package_name: str) -> str:
    """Return a minimal Connect bundle manifest for an R package install check."""
    return json.dumps(
        {
            "version": 1,
            "locale": "en_US",
            "platform": "4.4.0",
            "metadata": {"appmode": "api", "primary_rmd": None, "primary_html": None},
            "packages": {
                package_name: {"Source": "CRAN", "Repository": "https://cran.r-project.org"}
            },
            "files": {"plumber.R": {"checksum": ""}},
        }
    )


_PLUMBER_R = '#* @get /\nfunction() list(status = "ok")\n'


@when(
    "I deploy a minimal content item that installs the R package",
    target_fixture="deploy_state",
)
def deploy_r_package(connect_client, r_package_name, vip_config):
    content_name = f"vip_test_r_pkg_{r_package_name.lower()}_check"
    content = connect_client.create_content(
        content_name,
        description=f"VIP package install check for {r_package_name}",
        access_type="acl",
        tags=["_vip_test"],
    )
    guid = content["guid"]

    bundle_files = {
        "plumber.R": _PLUMBER_R,
        "manifest.json": _r_package_manifest(r_package_name),
    }
    bundle_bytes = _make_tar_gz(bundle_files)
    bundle = connect_client.upload_bundle(guid, bundle_bytes)
    result = connect_client.deploy_bundle(guid, bundle["id"])
    task_id = result["task_id"]

    timeout = vip_config.connect.deploy_timeout
    task = connect_client.wait_for_task(task_id, timeout=timeout)
    if not task.get("finished"):
        output = "\n".join(task.get("output", []))
        pytest.fail(
            f"Deployment did not complete within {timeout} seconds\n\n--- Task output ---\n{output}"
        )
    if task.get("code") != 0:
        output = "\n".join(task.get("output", []))
        error = task.get("error", "unknown error")
        pytest.fail(f"Deployment failed: {error}\n\n--- Task output ---\n{output}")

    return {"guid": guid, "task_result": task}


def _python_package_manifest(package_name: str) -> str:
    """Return a minimal Connect bundle manifest for a Python package install check."""
    return json.dumps(
        {
            "version": 1,
            "locale": "en_US",
            "metadata": {"appmode": "python-api", "entry_point": "app:app"},
            "python": {"version": "3.11.0", "package_manager": {"name": "pip", "version": "24.0"}},
            "packages": {package_name: {"Source": "PyPI", "Version": "latest"}},
            "files": {"app.py": {"checksum": ""}},
        }
    )


_FLASK_APP_PY = (
    "from flask import Flask\n"
    "app = Flask(__name__)\n\n"
    '@app.route("/")\n'
    "def index():\n"
    '    return {"status": "ok"}\n'
)


@when(
    "I deploy a minimal content item that installs the Python package",
    target_fixture="deploy_state",
)
def deploy_python_package(connect_client, python_package_name, vip_config):
    content_name = f"vip_test_py_pkg_{python_package_name.lower()}_check"
    content = connect_client.create_content(
        content_name,
        description=f"VIP package install check for {python_package_name}",
        access_type="acl",
        tags=["_vip_test"],
    )
    guid = content["guid"]

    bundle_files = {
        "app.py": _FLASK_APP_PY,
        "manifest.json": _python_package_manifest(python_package_name),
    }
    bundle_bytes = _make_tar_gz(bundle_files)
    bundle = connect_client.upload_bundle(guid, bundle_bytes)
    result = connect_client.deploy_bundle(guid, bundle["id"])
    task_id = result["task_id"]

    timeout = vip_config.connect.deploy_timeout
    task = connect_client.wait_for_task(task_id, timeout=timeout)
    if not task.get("finished"):
        output = "\n".join(task.get("output", []))
        pytest.fail(
            f"Deployment did not complete within {timeout} seconds\n\n--- Task output ---\n{output}"
        )
    if task.get("code") != 0:
        output = "\n".join(task.get("output", []))
        error = task.get("error", "unknown error")
        pytest.fail(f"Deployment failed: {error}\n\n--- Task output ---\n{output}")

    return {"guid": guid, "task_result": task}


@when(
    "I install the R package in the terminal",
    target_fixture="install_output",
)
def install_r_package_workbench(page, r_package_name):
    cmd = (
        f"Rscript -e \"install.packages('{r_package_name}', "
        f"repos='https://cran.r-project.org', quiet=TRUE)\" 2>&1 || true"
    )
    return terminal_run(page, cmd, timeout=120_000)


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then("all expected R versions are present on Connect")
def r_versions_present(expected_r_versions, available_r):
    missing = [v for v in expected_r_versions if v not in available_r]
    assert not missing, f"Missing R versions on Connect: {missing}. Available: {available_r}"


@then("all expected Python versions are present on Connect")
def python_versions_present(expected_python_versions, available_python):
    missing = [v for v in expected_python_versions if v not in available_python]
    assert not missing, (
        f"Missing Python versions on Connect: {missing}. Available: {available_python}"
    )


@then("the deployment succeeds")
def deployment_succeeds(deploy_state):
    # deploy_bundle raises on task failure (handled in the When step);
    # reaching here means the deployment completed successfully.
    assert deploy_state.get("guid"), "No GUID recorded for deployed content"


@then("I clean up the deployed content")
def cleanup_deployed_content(deploy_state, connect_client):
    guid = deploy_state.get("guid")
    if guid:
        connect_client.cleanup_content([guid])


@then("the installation succeeds")
def r_install_succeeds(install_output, r_package_name):
    # Rscript exits 0 on success. If the package was not found or install
    # failed, the output typically contains "ERROR" or "Warning message".
    lowered = install_output.lower()
    assert "error" not in lowered and "warning" not in lowered, (
        f"R package installation may have failed. Output:\n{install_output}"
    )
