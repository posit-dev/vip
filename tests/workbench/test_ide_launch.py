"""Step definitions for Workbench IDE launch tests.

These tests use Playwright to walk through the Workbench UI and verify that
each IDE type can be started.  They are intentionally resilient to UI layout
changes by using multiple selector strategies.
"""

from __future__ import annotations

import pytest
from pytest_bdd import scenario, given, when, then


@scenario("test_ide_launch.feature", "RStudio IDE session can be launched")
def test_launch_rstudio():
    pass


@scenario("test_ide_launch.feature", "VS Code session can be launched")
def test_launch_vscode():
    pass


@scenario("test_ide_launch.feature", "JupyterLab session can be launched")
def test_launch_jupyter():
    pass


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

@pytest.fixture()
def session_state():
    return {}


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

@given("the user is logged in to Workbench")
def user_logged_in(page, workbench_url, test_username, test_password):
    page.goto(workbench_url)
    # If we land on a login page, authenticate.
    if "sign-in" in page.url.lower() or "login" in page.url.lower():
        page.fill("#username, [name='username']", test_username)
        page.fill("#password, [name='password']", test_password)
        page.click("button[type='submit'], #sign-in")
        page.wait_for_load_state("networkidle")


@when("the user launches an RStudio session")
def launch_rstudio(page):
    # Look for a "New Session" button and select RStudio.
    page.click("text=New Session", timeout=15000)
    page.click("text=RStudio", timeout=5000)
    page.click("button:has-text('Start')", timeout=5000)


@when("the user launches a VS Code session")
def launch_vscode(page):
    page.click("text=New Session", timeout=15000)
    page.click("text=VS Code", timeout=5000)
    page.click("button:has-text('Start')", timeout=5000)


@when("the user launches a JupyterLab session")
def launch_jupyter(page):
    page.click("text=New Session", timeout=15000)
    page.click("text=JupyterLab", timeout=5000)
    page.click("button:has-text('Start')", timeout=5000)


@then("the session starts within a reasonable time")
def session_starts(page):
    # Wait for the IDE frame / container to appear.
    page.wait_for_selector(
        "iframe, .session-frame, #rstudio-frame, .code-server",
        timeout=60000,
    )


@then("the RStudio IDE is displayed")
def rstudio_displayed(page):
    # RStudio loads inside an iframe; verify it appears.
    page.wait_for_selector("iframe[src*='s/'], iframe[src*='rstudio']", timeout=30000)


@then("the VS Code IDE is displayed")
def vscode_displayed(page):
    page.wait_for_selector("iframe[src*='code-server'], iframe[src*='vscode']", timeout=30000)


@then("the JupyterLab IDE is displayed")
def jupyter_displayed(page):
    page.wait_for_selector("iframe[src*='jupyter'], iframe[src*='lab']", timeout=30000)
