"""Step definitions for Workbench IDE launch tests.

These tests verify that each IDE type can be started and becomes functional.
Patterns adapted from rstudio-pro/e2e tests.
"""

from __future__ import annotations

import time

import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import given, scenario, then, when

from tests.workbench.conftest import workbench_login
from tests.workbench.pages import (
    Homepage,
    JupyterLabSession,
    NewSessionDialog,
    PositronSession,
    RStudioSession,
    VSCodeSession,
)


@scenario("test_ide_launch.feature", "RStudio IDE session can be launched")
def test_launch_rstudio():
    pass


@scenario("test_ide_launch.feature", "VS Code session can be launched")
def test_launch_vscode():
    pass


@scenario("test_ide_launch.feature", "JupyterLab session can be launched")
def test_launch_jupyter():
    pass


@scenario("test_ide_launch.feature", "Positron session can be launched")
def test_launch_positron():
    pass


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------


@pytest.fixture
def session_context():
    """Holds session name across steps."""
    return {"name": None, "ide_type": None}


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@given("the user is logged in to Workbench")
def user_logged_in(
    page: Page,
    workbench_url: str,
    test_username: str,
    test_password: str,
    auth_provider: str,
    interactive_auth: bool,
):
    """Log in to Workbench and verify homepage loads."""
    workbench_login(
        page, workbench_url, test_username, test_password, auth_provider, interactive_auth
    )

    # Verify homepage elements (use .first for NEW_SESSION_BUTTON as there can be two)
    expect(page.locator(Homepage.POSIT_LOGO)).to_be_visible(timeout=15000)
    expect(page.locator(Homepage.NEW_SESSION_BUTTON).first).to_be_visible(timeout=15000)


@when("the user starts a new RStudio session")
def start_rstudio_session(page: Page, session_context: dict):
    """Start a new RStudio session using the new session dialog."""
    session_name = f"VIP Test RStudio {int(time.time())}"
    session_context["name"] = session_name
    session_context["ide_type"] = "RStudio"
    _start_session(page, "RStudio", session_name)


@when("the user starts a new VS Code session")
def start_vscode_session(page: Page, session_context: dict):
    """Start a new VS Code session using the new session dialog."""
    session_name = f"VIP Test VS Code {int(time.time())}"
    session_context["name"] = session_name
    session_context["ide_type"] = "VS Code"
    _start_session(page, "VS Code", session_name)


@when("the user starts a new JupyterLab session")
def start_jupyter_session(page: Page, session_context: dict):
    """Start a new JupyterLab session using the new session dialog."""
    session_name = f"VIP Test JupyterLab {int(time.time())}"
    session_context["name"] = session_name
    session_context["ide_type"] = "JupyterLab"
    _start_session(page, "JupyterLab", session_name)


@when("the user starts a new Positron session")
def start_positron_session(page: Page, session_context: dict):
    """Start a new Positron session using the new session dialog."""
    session_name = f"VIP Test Positron {int(time.time())}"
    session_context["name"] = session_name
    session_context["ide_type"] = "Positron"
    _start_session(page, "Positron", session_name)


def _start_session(page: Page, ide_type: str, session_name: str):
    """Start a new session using rstudio-pro dialog patterns.

    Note: We intentionally UNCHECK auto-join so we can observe the session
    state transitions on the homepage before navigating into the session.
    """
    page.locator(Homepage.NEW_SESSION_BUTTON).first.click(timeout=10000)

    dialog = page.locator(NewSessionDialog.DIALOG)
    expect(dialog.locator(NewSessionDialog.TITLE)).to_have_text("New Session", timeout=10000)

    # Select IDE type using role-based selector within dialog
    ide_display = NewSessionDialog.ide_display_name(ide_type)
    dialog.get_by_role("tab", name=ide_display).click(timeout=5000)

    page.fill(NewSessionDialog.SESSION_NAME, session_name)

    # Uncheck auto-join so we stay on homepage to observe state transitions
    checkbox = page.locator(NewSessionDialog.JOIN_CHECKBOX)
    if checkbox.is_checked():
        checkbox.click()
    expect(checkbox).not_to_be_checked(timeout=5000)

    page.locator(NewSessionDialog.LAUNCH_BUTTON).click(timeout=5000)


@then("the session transitions to Active state")
def session_becomes_active(page: Page, session_context: dict):
    """Verify session transitions from Starting to Active."""
    session_name = session_context["name"]

    # Verify our session appears on the homepage
    session_text = page.get_by_text(session_name, exact=True)
    expect(session_text).to_be_visible(timeout=15000)

    # Wait for session to reach Active state (may skip Starting if fast)
    # Using .first() since there may be multiple Active sessions from prior tests
    expect(page.get_by_role("button", name="Active").first).to_be_visible(timeout=90000)

    # Navigate into the session
    session_link = page.get_by_role("link", name=session_name)
    expect(session_link).to_be_visible(timeout=10000)
    session_link.click()


@then("the RStudio IDE is displayed and functional")
def rstudio_functional(page: Page):
    """Verify RStudio IDE core elements are visible."""
    expect(page.locator(RStudioSession.LOGO)).to_be_visible(timeout=30000)
    expect(page.locator(RStudioSession.CONTAINER)).to_be_visible(timeout=10000)
    expect(page.locator(RStudioSession.PROJECT_MENU)).to_be_visible(timeout=10000)


@then("the VS Code IDE is displayed")
def vscode_displayed(page: Page):
    """Verify VS Code IDE core elements are visible."""
    expect(page.locator(VSCodeSession.WORKBENCH)).to_be_visible(timeout=60000)
    expect(page.locator(VSCodeSession.STATUS_BAR)).to_be_visible(timeout=10000)


@then("the JupyterLab IDE is displayed")
def jupyter_displayed(page: Page):
    """Verify JupyterLab IDE core elements are visible."""
    expect(page.locator(JupyterLabSession.LAUNCHER)).to_be_visible(timeout=60000)


@then("the Positron IDE is displayed")
def positron_displayed(page: Page):
    """Verify Positron IDE core elements are visible."""
    expect(page.locator(PositronSession.WORKBENCH)).to_be_visible(timeout=60000)
    expect(page.locator(PositronSession.STATUS_BAR)).to_be_visible(timeout=10000)


@then("the session is cleaned up")
def session_cleaned_up(page: Page, workbench_url: str, session_context: dict):
    """Navigate back to homepage and quit the session."""
    session_name = session_context["name"]

    # Navigate back to homepage (use /home to avoid login redirect)
    home_url = workbench_url.rstrip("/") + "/home"
    page.goto(home_url)
    expect(page.locator(Homepage.POSIT_LOGO)).to_be_visible(timeout=15000)

    # Select the session checkbox
    checkbox = page.locator(Homepage.session_checkbox(session_name))
    expect(checkbox).to_be_visible(timeout=10000)
    checkbox.click()

    # Click Quit button
    quit_btn = page.locator(Homepage.QUIT_BUTTON)
    expect(quit_btn).to_be_visible(timeout=5000)
    quit_btn.click()

    # Wait for session to disappear from the list
    session_link = page.locator(Homepage.session_link(session_name))
    expect(session_link).not_to_be_visible(timeout=30000)
