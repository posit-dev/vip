"""Step definitions for Connect content deployment tests.

Each scenario creates, deploys, verifies, and deletes a content item so that
the tests are non-destructive.  All content is tagged with ``_vip_test`` for
easy identification and cleanup.
"""

from __future__ import annotations

import io
import json
import pathlib
import tarfile
import time

import httpx
import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_content_deploy.feature", "Deploy and execute a Quarto document")
def test_deploy_quarto():
    pass


@scenario("test_content_deploy.feature", "Deploy and execute a Plumber API")
def test_deploy_plumber():
    pass


@scenario("test_content_deploy.feature", "Deploy and execute a Shiny application")
def test_deploy_shiny():
    pass


@scenario("test_content_deploy.feature", "Deploy and execute a Dash application")
def test_deploy_dash():
    pass


# ---------------------------------------------------------------------------
# Shared state for the current scenario
# ---------------------------------------------------------------------------


@pytest.fixture()
def deploy_state():
    """Mutable dict to carry state across steps within a single scenario."""
    return {}


# ---------------------------------------------------------------------------
# Bundle helpers
# ---------------------------------------------------------------------------


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


_QUARTO_BUNDLE = {
    "index.qmd": "---\ntitle: VIP Test\n---\n\nHello from VIP.\n",
    "manifest.json": json.dumps(
        {
            "version": 1,
            "metadata": {"appmode": "quarto-static", "primary_document": "index.qmd"},
            "quarto": {"engines": ["markdown"]},
        }
    ),
}

_PLUMBER_BUNDLE = {
    "plumber.R": ('#* @get /\nfunction() {\n  list(message = "VIP test OK")\n}\n'),
    "manifest.json": (pathlib.Path(__file__).parent / "plumber_manifest.json").read_text(),
}

_SHINY_BUNDLE = {
    "app.R": (
        "library(shiny)\n"
        'ui <- fluidPage("VIP test")\n'
        "server <- function(input, output, session) {}\n"
        "shinyApp(ui, server)\n"
    ),
    "manifest.json": json.dumps(
        {
            "version": 1,
            "metadata": {"appmode": "shiny", "entrypoint": "app.R"},
            "packages": {"shiny": {"Source": "CRAN"}},
        }
    ),
}

_DASH_BUNDLE = {
    "app.py": (
        'from dash import Dash, html\napp = Dash(__name__)\napp.layout = html.Div("VIP test")\n'
    ),
    "manifest.json": json.dumps(
        {
            "version": 1,
            "metadata": {"appmode": "python-dash", "entrypoint": "app.py"},
            "python": {"version": "3.11"},
            "packages": {"dash": {"source": "pip"}},
        }
    ),
}

_BUNDLES: dict[str, dict[str, str]] = {
    "vip-quarto-test": _QUARTO_BUNDLE,
    "vip-plumber-test": _PLUMBER_BUNDLE,
    "vip-shiny-test": _SHINY_BUNDLE,
    "vip-dash-test": _DASH_BUNDLE,
}


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@given("Connect is accessible at the configured URL")
def connect_accessible(connect_client):
    assert connect_client is not None


@when('I create a VIP test content item named "vip-quarto-test"', target_fixture="deploy_state")
@when('I create a VIP test content item named "vip-plumber-test"', target_fixture="deploy_state")
@when('I create a VIP test content item named "vip-shiny-test"', target_fixture="deploy_state")
@when('I create a VIP test content item named "vip-dash-test"', target_fixture="deploy_state")
def create_content(connect_client, request):
    # Extract content name by matching the content type keyword (e.g., "plumber")
    # from the bundle name against the test function name (e.g., "test_deploy_plumber").
    test_name = request.node.name
    for name in _BUNDLES:
        # "vip-plumber-test" → "plumber", "vip-shiny-test" → "shiny", etc.
        content_type = name.split("-")[1]
        if content_type in test_name:
            content = connect_client.create_content(name)
            return {
                "guid": content["guid"],
                "name": name,
                "content_url": content.get("content_url", ""),
            }
    pytest.fail(f"No bundle configuration found matching test: {test_name}")


@when("I upload and deploy a minimal Quarto bundle")
@when("I upload and deploy a minimal Plumber bundle")
@when("I upload and deploy a minimal Shiny bundle")
@when("I upload and deploy a minimal Dash bundle")
def upload_and_deploy(connect_client, deploy_state):
    name = deploy_state["name"]
    bundle_files = _BUNDLES.get(name, _QUARTO_BUNDLE)
    archive = _make_tar_gz(bundle_files)
    bundle = connect_client.upload_bundle(deploy_state["guid"], archive)
    deploy_state["bundle_id"] = bundle["id"]
    result = connect_client.deploy_bundle(deploy_state["guid"], bundle["id"])
    deploy_state["task_id"] = result["task_id"]


@when("I wait for the deployment to complete")
def wait_for_deploy(connect_client, deploy_state):
    task_id = deploy_state["task_id"]
    deadline = time.time() + 120  # 2-minute timeout
    while time.time() < deadline:
        task = connect_client.get_task(task_id)
        if task.get("finished"):
            deploy_state["task_result"] = task
            assert task.get("code") == 0, f"Deployment failed: {task.get('error', 'unknown error')}"
            return
        time.sleep(3)
    pytest.fail("Deployment did not complete within 120 seconds")


@then("the content is accessible via HTTP")
def content_accessible(connect_client, deploy_state):
    content = connect_client.get_content(deploy_state["guid"])
    url = content.get("content_url", "")
    if url:
        resp = httpx.get(url, follow_redirects=True, timeout=30)
        assert resp.status_code < 400, f"Content returned HTTP {resp.status_code}"


@then("I clean up the test content")
def cleanup_content(connect_client, deploy_state):
    connect_client.delete_content(deploy_state["guid"])
