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
    LOGIN_ERROR = "#errorpanel"
    LOGIN_ERROR_TEXT = "#errortext"

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

    # RStudio IDE (ide_base.page.ts, rstudio_session.page.ts)
    RSTUDIO_LOGO = "#rstudio_rstudio_logo"
    RSTUDIO_CONTAINER = "#rstudio_container"
    PROJECT_MENU = "#rstudio_project_menubutton_toolbar"
    CONSOLE_OUTPUT = "#rstudio_console_output"
    CONSOLE_INPUT = "#rstudio_console_input"

    # VS Code
    VSCODE_WORKBENCH = ".monaco-workbench"
    VSCODE_STATUS_BAR = ".statusbar"

    # JupyterLab
    JUPYTER_LAUNCHER = ".jp-Launcher"
    JUPYTER_NOTEBOOK = ".jp-NotebookPanel"

    # IDE name mapping for new session dialog tabs
    IDE_NAMES = {
        "RStudio": "RStudio Pro",
        "VS Code": "VS Code",
        "JupyterLab": "JupyterLab",
        "Positron": "Positron",
    }

    @staticmethod
    def ide_display_name(ide_name: str) -> str:
        """Get the display name for an IDE type in the new session dialog."""
        return WorkbenchSelectors.IDE_NAMES.get(ide_name, ide_name)

    @staticmethod
    def session_state(state: str) -> str:
        """Selector for session state button."""
        return f"button:text-is('{state}')"

    @staticmethod
    def session_link(name: str) -> str:
        """Selector for session link by name."""
        return f"a[title='{name}'], a:text-is('{name}')"

    @staticmethod
    def session_checkbox(name: str) -> str:
        """Selector for session selection checkbox."""
        return f"[aria-label='select {name}']"


# ---------------------------------------------------------------------------
# Login Helper
# ---------------------------------------------------------------------------


def workbench_login(
    page: Page,
    workbench_url: str,
    username: str,
    password: str,
    *,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> None:
    """Navigate to Workbench homepage, logging in only if required.

    This function:
    - Navigates directly to /home to reuse existing sessions
    - Only logs in if redirected to the login page
    - Retries on transient server errors

    Args:
        page: Playwright page object
        workbench_url: Base URL for Workbench (e.g., http://localhost:8787)
        username: Login username
        password: Login password
        max_retries: Max login attempts on transient errors (default 3)
        retry_delay: Seconds to wait between retries (default 2.0)
    """
    # Navigate directly to /home to reuse existing session
    home_url = workbench_url.rstrip("/") + "/home"

    login_form = page.locator(WorkbenchSelectors.LOGIN_USERNAME)
    homepage_logo = page.locator(WorkbenchSelectors.POSIT_LOGO)
    either_visible = login_form.or_(homepage_logo)

    for attempt in range(max_retries):
        if attempt > 0:
            time.sleep(retry_delay)

        page.goto(home_url)
        either_visible.wait_for(timeout=15000)

        # Already logged in - done
        if homepage_logo.is_visible():
            return

        # Not on login page either - something unexpected, retry
        if not login_form.is_visible():
            continue

        # Redirected to login - need to authenticate
        page.fill(WorkbenchSelectors.LOGIN_USERNAME, username)
        page.fill(WorkbenchSelectors.LOGIN_PASSWORD, password)

        # Check "stay signed in" to preserve session between tests
        stay_signed_in = page.locator(WorkbenchSelectors.LOGIN_STAY_SIGNED_IN)
        if stay_signed_in.is_visible() and not stay_signed_in.is_checked():
            stay_signed_in.click()

        page.click(WorkbenchSelectors.LOGIN_BUTTON)

        either_visible.wait_for(timeout=15000)

        if homepage_logo.is_visible():
            return  # Success

        # Still on login page - capture error on final attempt
        if attempt == max_retries - 1:
            error_panel = page.locator(WorkbenchSelectors.LOGIN_ERROR)
            if error_panel.is_visible():
                error_text = page.locator(WorkbenchSelectors.LOGIN_ERROR_TEXT).text_content()
                raise AssertionError(f"Login failed: {error_text or 'Unknown error'}")
            raise AssertionError(f"Login failed after {max_retries} attempts")

    raise AssertionError(f"Login failed after {max_retries} attempts")


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
    Handles both fresh login and already-authenticated sessions.
    Returns the page for further interactions.
    """
    workbench_login(page, workbench_url, test_username, test_password)

    # Verify homepage elements
    expect(page.locator(WorkbenchSelectors.POSIT_LOGO)).to_be_visible(timeout=15000)
    expect(page.locator(WorkbenchSelectors.NEW_SESSION_BUTTON)).to_be_visible(timeout=15000)

    return page


@pytest.fixture
def wb_start_session(page: Page, wb_login):
    """Factory fixture to start a session of any IDE type.

    Usage:
        def test_example(wb_start_session):
            session_name = wb_start_session("RStudio")

            # Or with auto_join disabled to stay on homepage:
            session_name = wb_start_session("RStudio", auto_join=False)
    """

    def _start(ide_type: str, session_name: str | None = None, *, auto_join: bool = True) -> str:
        if session_name is None:
            session_name = f"VIP Test {ide_type} {int(time.time())}"

        page.locator(WorkbenchSelectors.NEW_SESSION_BUTTON).click(timeout=10000)

        # Wait for dialog to appear
        dialog = page.locator(WorkbenchSelectors.DIALOG)
        expect(dialog.locator(WorkbenchSelectors.DIALOG_TITLE)).to_have_text(
            "New Session", timeout=10000
        )

        # Select IDE type using role-based selector within dialog
        ide_display = WorkbenchSelectors.ide_display_name(ide_type)
        dialog.get_by_role("tab", name=ide_display).click(timeout=5000)

        # Set session name
        page.fill(WorkbenchSelectors.SESSION_NAME_INPUT, session_name)

        # Set auto-join checkbox based on parameter
        checkbox = page.locator(WorkbenchSelectors.JOIN_CHECKBOX)
        if auto_join and not checkbox.is_checked():
            checkbox.click()
        elif not auto_join and checkbox.is_checked():
            checkbox.click()

        # Launch the session
        page.locator(WorkbenchSelectors.LAUNCH_BUTTON).click(timeout=5000)

        # Wait for session to become active
        expect(page.get_by_text(session_name, exact=True)).to_be_visible(timeout=15000)
        expect(page.get_by_role("button", name="Active").first).to_be_visible(timeout=90000)

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
