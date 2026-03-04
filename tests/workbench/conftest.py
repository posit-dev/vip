"""Workbench-specific fixtures and helpers.

Selectors and patterns adapted from rstudio-pro/e2e/pages/ page objects.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

if TYPE_CHECKING:
    pass

pytestmark = pytest.mark.workbench


# ---------------------------------------------------------------------------
# Workbench Selectors (from rstudio-pro/e2e/pages/)
# ---------------------------------------------------------------------------


class WorkbenchSelectors:
    """Centralized selectors matching rstudio-pro page objects."""

    # Login page (login.page.ts)
    LOGIN_USERNAME = "#username"
    LOGIN_PASSWORD = "#password"
    LOGIN_BUTTON = "#signinbutton"
    LOGIN_STAY_SIGNED_IN = "#staySignedIn"

    # Homepage (homepage.page.ts)
    POSIT_LOGO = "#posit-logo"
    CURRENT_USER = "#current-user"
    NEW_SESSION_BUTTON = "button:text-is('New Session')"
    PROJECTS_TAB = "a:text-is('Projects')"
    JOBS_TAB = "a:text-is('Jobs')"
    QUIT_BUTTON = "button:text-is('Quit')"
    SUSPEND_BUTTON = "button:text-is('Suspend')"
    NO_PROJECTS = "text=No projects"
    SIGN_OUT_FORM = "form[action*='sign-out']"

    # New Session Dialog
    DIALOG = "[role='dialog']"
    DIALOG_TITLE = "[data-slot='dialog-title']"
    SESSION_NAME_INPUT = "input#rstudio_label_session_name"
    JOIN_CHECKBOX = "#modal-auto-join-button"
    LAUNCH_BUTTON = "button:text-is('Launch')"

    # RStudio IDE (ide_base.page.ts)
    RSTUDIO_LOGO = "#rstudio_logo"
    RSTUDIO_CONTAINER = "#rstudio_container"
    PROJECT_MENU = "#rstudio_project_menu_label"
    CONSOLE_OUTPUT = "#rstudio_console_output"
    CONSOLE_INPUT = "#rstudio_console_input"

    # VS Code
    VSCODE_WORKBENCH = ".monaco-workbench"
    VSCODE_STATUS_BAR = ".statusbar"

    # JupyterLab
    JUPYTER_LAUNCHER = ".jp-Launcher"
    JUPYTER_NOTEBOOK = ".jp-NotebookPanel"

    @staticmethod
    def ide_tab(ide_name: str) -> str:
        """Selector for IDE tab in new session dialog."""
        name_map = {
            "RStudio": "RStudio Pro",
            "VS Code": "VS Code",
            "JupyterLab": "JupyterLab",
            "Positron": "Positron",
        }
        ui_name = name_map.get(ide_name, ide_name)
        return f"[id*='trigger-{ui_name.replace(' ', '')}'], button[aria-label*='{ui_name}']"

    @staticmethod
    def session_state(state: str) -> str:
        """Selector for session state button."""
        return f"button:has-text('{state}')"

    @staticmethod
    def session_link(name: str) -> str:
        """Selector for session link by name."""
        return f"a[title='{name}'], a:has-text('{name}')"

    @staticmethod
    def session_checkbox(name: str) -> str:
        """Selector for session selection checkbox."""
        return f"[aria-label='select {name}']"


# ---------------------------------------------------------------------------
# Shared Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def wb_selectors() -> type[WorkbenchSelectors]:
    """Provide access to WorkbenchSelectors class."""
    return WorkbenchSelectors


@pytest.fixture
def wb_login(page: Page, workbench_url: str, test_username: str, test_password: str):
    """Log in to Workbench and verify homepage loads.

    This fixture handles the complete login flow using rstudio-pro patterns.
    Returns the page for further interactions.
    """
    page.goto(workbench_url)

    # Wait for login form to appear
    page.wait_for_selector(WorkbenchSelectors.LOGIN_USERNAME, timeout=15000)

    # Fill credentials and submit
    page.fill(WorkbenchSelectors.LOGIN_USERNAME, test_username)
    page.fill(WorkbenchSelectors.LOGIN_PASSWORD, test_password)
    page.click(WorkbenchSelectors.LOGIN_BUTTON)
    page.wait_for_load_state("networkidle")

    # Verify homepage loaded (not just "not on login page")
    expect(page.locator(WorkbenchSelectors.POSIT_LOGO)).to_be_visible(timeout=15000)
    expect(page.locator(WorkbenchSelectors.NEW_SESSION_BUTTON)).to_be_visible(timeout=15000)

    return page


@pytest.fixture
def wb_start_session(page: Page, wb_login):
    """Factory fixture to start a session of any IDE type.

    Usage:
        def test_example(wb_start_session):
            session_name = wb_start_session("RStudio")
    """

    def _start(ide_type: str, session_name: str | None = None) -> str:
        if session_name is None:
            session_name = f"VIP Test {ide_type} {int(time.time())}"

        page.locator(WorkbenchSelectors.NEW_SESSION_BUTTON).click(timeout=10000)

        # Wait for dialog to appear
        dialog = page.locator(WorkbenchSelectors.DIALOG)
        expect(dialog.locator(WorkbenchSelectors.DIALOG_TITLE)).to_have_text(
            "New Session", timeout=10000
        )

        # Select IDE type
        page.click(WorkbenchSelectors.ide_tab(ide_type), timeout=5000)

        # Set session name
        page.fill(WorkbenchSelectors.SESSION_NAME_INPUT, session_name)

        # Ensure auto-join is checked
        checkbox = page.locator(WorkbenchSelectors.JOIN_CHECKBOX)
        if not checkbox.is_checked():
            checkbox.click()

        # Launch the session
        page.click(WorkbenchSelectors.LAUNCH_BUTTON, timeout=5000)

        # Wait for session to become active
        page.wait_for_selector(WorkbenchSelectors.session_state("Starting"), timeout=20000)
        page.wait_for_selector(WorkbenchSelectors.session_state("Active"), timeout=90000)

        return session_name

    return _start


@pytest.fixture
def wb_quit_session(page: Page):
    """Factory fixture to quit a session by name."""

    def _quit(session_name: str):
        checkbox = page.locator(WorkbenchSelectors.session_checkbox(session_name))
        checkbox.click()

        quit_btn = page.locator(WorkbenchSelectors.QUIT_BUTTON)
        expect(quit_btn).to_be_visible()
        quit_btn.click()

        # Wait for session to disappear
        expect(page.locator(WorkbenchSelectors.session_link(session_name))).not_to_be_visible(
            timeout=30000
        )

    return _quit
