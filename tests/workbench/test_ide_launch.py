"""Step definitions for Workbench IDE launch tests.

These tests verify that each IDE type can be started and becomes functional.
Patterns adapted from rstudio-pro/e2e tests.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import given, scenario, then, when

from tests.workbench.conftest import (
    TIMEOUT_CLEANUP,
    TIMEOUT_DIALOG,
    TIMEOUT_IDE_LOAD,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_QUICK,
    TIMEOUT_SESSION_START,
    assert_homepage_loaded,
    workbench_login,
)
from tests.workbench.pages import (
    Homepage,
    JupyterLabSession,
    NewSessionDialog,
    PositronSession,
    RStudioSession,
    VSCodeSession,
)

# Get filename for session naming
_FILENAME = Path(__file__).name


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

    assert_homepage_loaded(page)


def _start_ide_session(session_context: dict, page: Page, ide_name: str) -> None:
    """Set session context and start a new IDE session of the given type."""
    session_name = f"VIP {_FILENAME} - {int(time.time())}"
    session_context["name"] = session_name
    session_context["ide_type"] = ide_name
    _start_session(page, ide_name, session_name)


@when("the user starts a new RStudio session")
def start_rstudio_session(page: Page, session_context: dict):
    _start_ide_session(session_context, page, "RStudio")


@when("the user starts a new VS Code session")
def start_vscode_session(page: Page, session_context: dict):
    _start_ide_session(session_context, page, "VS Code")


@when("the user starts a new JupyterLab session")
def start_jupyter_session(page: Page, session_context: dict):
    _start_ide_session(session_context, page, "JupyterLab")


@when("the user starts a new Positron session")
def start_positron_session(page: Page, session_context: dict):
    _start_ide_session(session_context, page, "Positron")


def _start_session(page: Page, ide_type: str, session_name: str):
    """Start a new session using rstudio-pro dialog patterns.

    Note: We intentionally UNCHECK auto-join so we can observe the session
    state transitions on the homepage before navigating into the session.
    """
    page.locator(Homepage.NEW_SESSION_BUTTON).first.click(timeout=TIMEOUT_DIALOG)

    dialog = page.locator(NewSessionDialog.DIALOG)
    expect(dialog.locator(NewSessionDialog.TITLE)).to_have_text(
        "New Session", timeout=TIMEOUT_DIALOG
    )

    # Select IDE type using role-based selector within dialog
    ide_display = NewSessionDialog.ide_display_name(ide_type)
    dialog.get_by_role("tab", name=ide_display).click(timeout=TIMEOUT_QUICK)

    page.fill(NewSessionDialog.SESSION_NAME, session_name)

    # Uncheck auto-join so we stay on homepage to observe state transitions
    checkbox = page.locator(NewSessionDialog.JOIN_CHECKBOX)
    if checkbox.is_checked():
        checkbox.click()
    expect(checkbox).not_to_be_checked(timeout=TIMEOUT_QUICK)

    page.locator(NewSessionDialog.LAUNCH_BUTTON).click(timeout=TIMEOUT_QUICK)


@then("the session transitions to Active state")
def session_becomes_active(page: Page, session_context: dict):
    """Verify session transitions from Starting to Active."""
    session_name = session_context["name"]

    # Verify our session row appears on the homepage
    session_row = page.locator(Homepage.session_row(session_name))
    expect(session_row).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)

    # Wait for our session to reach Active state
    session_active = page.locator(Homepage.session_row_status(session_name, "Active"))
    expect(session_active).to_be_visible(timeout=TIMEOUT_SESSION_START)

    # Navigate into the session (link only appears when Active)
    session_link = session_row.locator(f"a[title='join {session_name}']")
    expect(session_link).to_be_visible(timeout=TIMEOUT_DIALOG)
    session_link.click()


@then("the RStudio IDE is displayed and functional")
def rstudio_functional(page: Page):
    """Verify RStudio IDE core elements are visible."""
    expect(page.locator(RStudioSession.LOGO)).to_be_visible(timeout=TIMEOUT_CLEANUP)
    expect(page.locator(RStudioSession.CONTAINER)).to_be_visible(timeout=TIMEOUT_DIALOG)
    expect(page.locator(RStudioSession.PROJECT_MENU)).to_be_visible(timeout=TIMEOUT_DIALOG)


@then("the VS Code IDE is displayed")
def vscode_displayed(page: Page):
    """Verify VS Code IDE core elements are visible."""
    expect(page.locator(VSCodeSession.WORKBENCH)).to_be_visible(timeout=TIMEOUT_IDE_LOAD)
    expect(page.locator(VSCodeSession.STATUS_BAR)).to_be_visible(timeout=TIMEOUT_DIALOG)


@then("the JupyterLab IDE is displayed")
def jupyter_displayed(page: Page):
    """Verify JupyterLab IDE core elements are visible."""
    expect(page.locator(JupyterLabSession.LAUNCHER)).to_be_visible(timeout=TIMEOUT_IDE_LOAD)


@then("the Positron IDE is displayed")
def positron_displayed(page: Page):
    """Verify Positron IDE core elements are visible."""
    expect(page.locator(PositronSession.WORKBENCH)).to_be_visible(timeout=TIMEOUT_IDE_LOAD)
    expect(page.locator(PositronSession.STATUS_BAR)).to_be_visible(timeout=TIMEOUT_DIALOG)


@then("the session is cleaned up")
def session_cleaned_up(page: Page, workbench_url: str, session_context: dict):
    """Navigate back to homepage and quit the session."""
    session_name = session_context["name"]

    # Navigate back to homepage (use /home to avoid login redirect)
    home_url = workbench_url.rstrip("/") + "/home"
    page.goto(home_url)
    expect(page.locator(Homepage.POSIT_LOGO)).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)

    # Select the session checkbox
    checkbox = page.locator(Homepage.session_checkbox(session_name))
    expect(checkbox).to_be_visible(timeout=TIMEOUT_DIALOG)
    checkbox.click()

    # Click Quit button
    quit_btn = page.locator(Homepage.QUIT_BUTTON)
    expect(quit_btn).to_be_visible(timeout=TIMEOUT_QUICK)
    quit_btn.click()

    # Wait for session to disappear from the list
    session_link = page.locator(Homepage.session_link(session_name))
    expect(session_link).not_to_be_visible(timeout=TIMEOUT_CLEANUP)
