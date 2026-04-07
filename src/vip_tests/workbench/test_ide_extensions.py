"""Step definitions for Workbench IDE extension validation tests.

These tests verify that the Posit Workbench extension is installed and visible
in VS Code, JupyterLab, and Positron sessions. All session lifecycle steps
(login, start, join, cleanup) are reused from test_ide_launch.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect
from pytest_bdd import scenario, then

from vip_tests.workbench.conftest import TIMEOUT_IDE_LOAD
from vip_tests.workbench.pages import JupyterLabSession, PositronSession, VSCodeSession

# Import shared steps so pytest-bdd registers them for this module
from vip_tests.workbench.test_ide_launch import (  # noqa: F401
    _FILENAME,
    jupyter_displayed,
    positron_displayed,
    session_becomes_active,
    session_cleaned_up,
    session_context,
    start_jupyter_session,
    start_positron_session,
    start_vscode_session,
    user_logged_in,
    vscode_displayed,
)


@scenario("test_ide_extensions.feature", "VS Code has the Posit Workbench extension")
def test_vscode_extension():
    pass


@scenario("test_ide_extensions.feature", "JupyterLab has the Posit Workbench extension")
def test_jupyterlab_extension():
    pass


@scenario("test_ide_extensions.feature", "Positron has the Posit Workbench extension")
def test_positron_extension():
    pass


# ---------------------------------------------------------------------------
# Extension-specific steps
# ---------------------------------------------------------------------------


@then("the Posit Workbench extension is visible in VS Code")
def vscode_has_posit_extension(page: Page):
    """Verify the Posit Workbench extension tab and home button are present."""
    tab = page.get_by_role("tab", name=VSCodeSession.POSIT_EXTENSION_TAB_NAME).locator("a")
    expect(tab).to_be_visible(timeout=TIMEOUT_IDE_LOAD)

    home_btn = page.get_by_role("button", name=VSCodeSession.POSIT_EXTENSION_HOME_BUTTON_NAME)
    expect(home_btn).to_be_visible(timeout=TIMEOUT_IDE_LOAD)


@then("the Posit Workbench extension is visible in JupyterLab")
def jupyterlab_has_posit_extension(page: Page):
    """Verify the Posit Workbench extension icon is present."""
    icon = page.locator(JupyterLabSession.POSIT_EXTENSION_ICON)
    expect(icon).to_be_visible(timeout=TIMEOUT_IDE_LOAD)


@then("the Posit Workbench extension is visible in Positron")
def positron_has_posit_extension(page: Page):
    """Verify the Posit Workbench extension tab and home button are present."""
    tab = page.get_by_role("tab", name=PositronSession.POSIT_EXTENSION_TAB_NAME).locator("a")
    expect(tab).to_be_visible(timeout=TIMEOUT_IDE_LOAD)

    home_btn = page.get_by_role("button", name=PositronSession.POSIT_EXTENSION_HOME_BUTTON_NAME)
    expect(home_btn).to_be_visible(timeout=TIMEOUT_IDE_LOAD)
