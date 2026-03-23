"""Step definitions for Connect content deployment tests.

Each scenario creates, deploys, verifies, and deletes a content item so that
the tests are non-destructive.  All content is tagged with ``_vip_test`` for
easy identification and cleanup.
"""

from __future__ import annotations

import json
import pathlib

import httpx
import pytest
from pytest_bdd import scenario, then, when

from tests.connect.conftest import _make_tar_gz

_GIT_REPO_URL = "https://github.com/posit-dev/connect-extensions"
# Using main branch — this is a Posit-maintained repo with stable examples.
# Connect's git integration requires a branch name (not a commit SHA).
_GIT_BRANCH = "main"
_GIT_DIRECTORY = "extensions/quarto-document"


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


@scenario("test_content_deploy.feature", "Deploy and execute an R Markdown document")
def test_deploy_rmarkdown():
    pass


@scenario("test_content_deploy.feature", "Deploy and execute a Jupyter Notebook")
def test_deploy_jupyter():
    pass


@scenario("test_content_deploy.feature", "Deploy and execute a FastAPI application")
def test_deploy_fastapi():
    pass


@scenario("test_content_deploy.feature", "Deploy and execute a git-backed Quarto document")
def test_deploy_gitbacked():
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


_PLUMBER_BUNDLE = {
    "plumber.R": ('#* @get /\nfunction() {\n  list(message = "VIP test OK")\n}\n'),
    "manifest.json": (pathlib.Path(__file__).parent / "plumber_manifest.json").read_text(),
}

# Bundles that need runtime versions are built dynamically in _get_bundle().
_STATIC_BUNDLES: dict[str, dict[str, str]] = {
    "vip-plumber-test": _PLUMBER_BUNDLE,
}


def _get_bundle(name: str, connect_client) -> dict[str, str]:
    """Return the bundle files for *name*, building manifests dynamically.

    Quarto, Shiny, and Dash manifests need real runtime versions from the
    server so they are constructed at test time rather than at import time.
    """
    if name in _STATIC_BUNDLES:
        return _STATIC_BUNDLES[name]

    if name == "vip-quarto-test":
        quarto_versions = connect_client.quarto_versions()
        if not quarto_versions:
            pytest.skip("No Quarto installations available on Connect")
        r_versions = connect_client.r_versions()
        manifest: dict = {
            "version": 1,
            "metadata": {
                "appmode": "quarto-static",
                "primary_document": "index.qmd",
                "content_category": "",
                "has_parameters": False,
            },
            "quarto": {
                "version": quarto_versions[0],
                "engines": ["markdown"],
            },
        }
        if r_versions:
            manifest["platform"] = r_versions[0]
        return {
            "index.qmd": "---\ntitle: VIP Test\n---\n\nHello from VIP.\n",
            "manifest.json": json.dumps(manifest),
        }

    if name == "vip-shiny-test":
        r_versions = connect_client.r_versions()
        if not r_versions:
            pytest.skip("No R versions available on Connect — cannot deploy Shiny")
        # Use the pre-built manifest with full dependency tree (like plumber).
        manifest = json.loads((pathlib.Path(__file__).parent / "shiny_manifest.json").read_text())
        manifest["platform"] = r_versions[0]
        return {
            "app.R": (
                "library(shiny)\n"
                'ui <- fluidPage("VIP test")\n'
                "server <- function(input, output, session) {}\n"
                "shinyApp(ui, server)\n"
            ),
            "manifest.json": json.dumps(manifest),
        }

    if name == "vip-dash-test":
        py_versions = connect_client.python_versions()
        if not py_versions:
            pytest.skip("No Python versions available on Connect — cannot deploy Dash")
        return {
            "app.py": (
                'import dash\napp = dash.Dash(__name__)\napp.layout = dash.html.Div("VIP test")\n'
            ),
            "requirements.txt": "dash\n",
            "manifest.json": json.dumps(
                {
                    "version": 1,
                    "metadata": {"appmode": "python-dash", "entrypoint": "app"},
                    "python": {
                        "version": py_versions[0],
                        "package_manager": {
                            "name": "pip",
                            "version": "24.0",
                            "package_file": "requirements.txt",
                        },
                    },
                }
            ),
        }

    if name == "vip-rmarkdown-test":
        r_versions = connect_client.r_versions()
        if not r_versions:
            pytest.skip("No R versions available on Connect — cannot deploy R Markdown")
        return {
            "index.Rmd": (
                "---\ntitle: VIP RMarkdown Test\noutput: html_document\n---\n\n"
                "Hello from VIP RMarkdown.\n"
            ),
            "manifest.json": json.dumps(
                {
                    "version": 1,
                    "platform": r_versions[0],
                    "metadata": {
                        "appmode": "rmd-static",
                        "primary_rmd": "index.Rmd",
                        "content_category": "",
                        "has_parameters": False,
                    },
                    "packages": {},
                }
            ),
        }

    if name == "vip-jupyter-test":
        py_versions = connect_client.python_versions()
        if not py_versions:
            pytest.skip("No Python versions available on Connect — cannot deploy Jupyter Notebook")
        notebook_content = json.dumps(
            {
                "nbformat": 4,
                "nbformat_minor": 5,
                "metadata": {
                    "kernelspec": {
                        "display_name": "Python 3",
                        "language": "python",
                        "name": "python3",
                    },
                    "language_info": {"name": "python", "version": py_versions[0]},
                },
                "cells": [
                    {
                        "cell_type": "code",
                        "execution_count": 1,
                        "metadata": {},
                        "outputs": [
                            {
                                "output_type": "stream",
                                "name": "stdout",
                                "text": "VIP notebook OK\n",
                            }
                        ],
                        "source": 'print("VIP notebook OK")',
                    }
                ],
            }
        )
        return {
            "notebook.ipynb": notebook_content,
            "manifest.json": json.dumps(
                {
                    "version": 1,
                    "metadata": {
                        "appmode": "jupyter-static",
                        "primary_document": "notebook.ipynb",
                        "content_category": "",
                        "has_parameters": False,
                    },
                    "python": {
                        "version": py_versions[0],
                        "package_manager": {
                            "name": "pip",
                            "version": "24.0",
                            "package_file": "requirements.txt",
                        },
                    },
                }
            ),
            "requirements.txt": "",
        }

    if name == "vip-fastapi-test":
        py_versions = connect_client.python_versions()
        if not py_versions:
            pytest.skip("No Python versions available on Connect — cannot deploy FastAPI")
        return {
            "app.py": (
                "from fastapi import FastAPI\n"
                "app = FastAPI()\n\n"
                "@app.get('/')\n"
                "def root():\n"
                '    return {"message": "VIP fastapi OK"}\n'
            ),
            "requirements.txt": "fastapi\nuvicorn\n",
            "manifest.json": json.dumps(
                {
                    "version": 1,
                    "metadata": {"appmode": "python-fastapi", "entrypoint": "app"},
                    "python": {
                        "version": py_versions[0],
                        "package_manager": {
                            "name": "pip",
                            "version": "24.0",
                            "package_file": "requirements.txt",
                        },
                    },
                }
            ),
        }

    pytest.fail(f"No bundle configuration for: {name}")


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


_CONTENT_NAMES = [
    "vip-quarto-test",
    "vip-plumber-test",
    "vip-shiny-test",
    "vip-dash-test",
    "vip-rmarkdown-test",
    "vip-jupyter-test",
    "vip-fastapi-test",
    "vip-gitbacked-test",
]


@when('I create a VIP test content item named "vip-quarto-test"', target_fixture="deploy_state")
@when('I create a VIP test content item named "vip-plumber-test"', target_fixture="deploy_state")
@when('I create a VIP test content item named "vip-shiny-test"', target_fixture="deploy_state")
@when('I create a VIP test content item named "vip-dash-test"', target_fixture="deploy_state")
@when('I create a VIP test content item named "vip-rmarkdown-test"', target_fixture="deploy_state")
@when('I create a VIP test content item named "vip-jupyter-test"', target_fixture="deploy_state")
@when('I create a VIP test content item named "vip-fastapi-test"', target_fixture="deploy_state")
@when('I create a VIP test content item named "vip-gitbacked-test"', target_fixture="deploy_state")
def create_content(connect_client, request):
    # Extract content name by matching the content type keyword (e.g., "plumber")
    # from the bundle name against the test function name (e.g., "test_deploy_plumber").
    test_name = request.node.name
    for name in _CONTENT_NAMES:
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
@when("I upload and deploy a minimal R Markdown bundle")
@when("I upload and deploy a minimal Jupyter Notebook bundle")
@when("I upload and deploy a minimal FastAPI bundle")
def upload_and_deploy(connect_client, deploy_state):
    name = deploy_state["name"]
    bundle_files = _get_bundle(name, connect_client)
    archive = _make_tar_gz(bundle_files)
    bundle = connect_client.upload_bundle(deploy_state["guid"], archive)
    deploy_state["bundle_id"] = bundle["id"]
    result = connect_client.deploy_bundle(deploy_state["guid"], bundle["id"])
    deploy_state["task_id"] = result["task_id"]


@when("I link the content item to a public test git repository")
def link_git_repository(connect_client, deploy_state):
    quarto_versions = connect_client.quarto_versions()
    if not quarto_versions:
        pytest.skip("No Quarto on Connect — cannot deploy git-backed Quarto document")
    # Check that the remote repository is reachable before attempting to link.
    try:
        resp = httpx.head(_GIT_REPO_URL, follow_redirects=True, timeout=10)
        if resp.status_code >= 400:
            pytest.skip(f"Git repository not reachable (HTTP {resp.status_code}): {_GIT_REPO_URL}")
    except httpx.TransportError as exc:
        pytest.skip(f"Git repository not reachable: {exc}")
    connect_client.set_repository(
        deploy_state["guid"], _GIT_REPO_URL, branch=_GIT_BRANCH, directory=_GIT_DIRECTORY
    )


@when("I trigger a git-backed deployment")
def trigger_git_deploy(connect_client, deploy_state):
    result = connect_client.deploy_from_repository(deploy_state["guid"])
    deploy_state["task_id"] = result["task_id"]


@when("I wait for the deployment to complete")
def wait_for_deploy(connect_client, deploy_state, vip_config):
    task_id = deploy_state["task_id"]
    timeout = vip_config.connect.deploy_timeout
    task = connect_client.wait_for_task(task_id, timeout=timeout)
    deploy_state["task_result"] = task
    if not task.get("finished"):
        output = "\n".join(task.get("output", []))
        pytest.fail(
            f"Deployment did not complete within {timeout} seconds\n\n--- Task output ---\n{output}"
        )
    if task.get("code") != 0:
        output = "\n".join(task.get("output", []))
        error = task.get("error", "unknown error")
        pytest.fail(f"Deployment failed: {error}\n\n--- Task output ---\n{output}")


@then("the content is accessible via HTTP")
def content_accessible(connect_client, deploy_state):
    content = connect_client.get_content(deploy_state["guid"])
    url = content.get("content_url", "")
    if url:
        resp = connect_client.fetch_content(url)
        assert resp.status_code < 400, f"Content returned HTTP {resp.status_code}"


# ---------------------------------------------------------------------------
# Expected-output markers for each content type
# ---------------------------------------------------------------------------

_EXPECTED_OUTPUT: dict[str, dict] = {
    # Quarto static renders an HTML page containing the document title and body.
    "vip-quarto-test": {
        "type": "html",
        "markers": ["VIP Test", "Hello from VIP"],
    },
    # Plumber GET / returns a JSON object with a "message" key.
    "vip-plumber-test": {
        "type": "json",
        "key": "message",
        "value": "VIP test OK",
    },
    # Shiny apps serve an HTML page with Shiny bootstrap markup.
    "vip-shiny-test": {
        "type": "html",
        "markers": ["shiny", "bootstraplib"],
    },
    # Dash apps serve an HTML page with Dash-specific markup.
    "vip-dash-test": {
        "type": "html",
        "markers": ["_dash-", "dash"],
    },
    # R Markdown static renders an HTML page containing the document title.
    "vip-rmarkdown-test": {
        "type": "html",
        "markers": ["VIP RMarkdown Test"],
    },
    # Jupyter static renders an HTML page with notebook output.
    "vip-jupyter-test": {
        "type": "html",
        "markers": ["VIP notebook OK"],
    },
    # FastAPI GET / returns a JSON object with a "message" key.
    "vip-fastapi-test": {
        "type": "json",
        "key": "message",
        "value": "VIP fastapi OK",
    },
    # posit-dev/connect-extensions quarto-document renders an HTML page.
    "vip-gitbacked-test": {
        "type": "html",
        "markers": ["Quarto Document", "Penguins"],
    },
}


@then("the content renders expected output")
def content_renders_expected_output(connect_client, deploy_state):
    name = deploy_state["name"]
    expected = _EXPECTED_OUTPUT.get(name)
    if expected is None:
        pytest.fail(f"No expected-output configuration for content: {name}")

    content = connect_client.get_content(deploy_state["guid"])
    url = content.get("content_url", "")
    if not url:
        pytest.skip("Content URL not available — skipping output verification")

    if expected["type"] == "json":
        # Plumber: append the route path and verify JSON response.
        resp = connect_client.fetch_content(url.rstrip("/") + "/")
        assert resp.status_code < 400, f"Plumber API returned HTTP {resp.status_code}"
        try:
            body = resp.json()
        except Exception as exc:
            pytest.fail(f"Plumber response is not valid JSON: {exc}\nBody: {resp.text[:500]}")
        # Connect wraps scalar values in lists; accept both "VIP test OK" and ["VIP test OK"].
        raw = body.get(expected["key"])
        value = raw[0] if isinstance(raw, list) else raw
        assert value == expected["value"], (
            f"Plumber response field '{expected['key']}' = {raw!r}; expected {expected['value']!r}"
        )

    else:
        # HTML content types: check that the page contains expected marker strings.
        resp = connect_client.fetch_content(url)
        assert resp.status_code < 400, f"Content page returned HTTP {resp.status_code}"
        body_lower = resp.text.lower()
        for marker in expected["markers"]:
            assert marker.lower() in body_lower, (
                f"Expected marker {marker!r} not found in response for {name}.\n"
                f"Response snippet: {resp.text[:500]}"
            )


@then("I clean up the test content")
def cleanup_content(connect_client, deploy_state):
    connect_client.delete_content(deploy_state["guid"])
