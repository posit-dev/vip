"""Step definitions for Workbench IDE extension validation tests.

These tests verify that the Posit Workbench extension is installed and visible
in VS Code, JupyterLab, and Positron sessions, plus any additional extensions
declared in vip.toml under [workbench.extensions].

All session lifecycle steps (login, start, join, cleanup) are reused from
test_ide_launch.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import scenario, then

from vip.config import VIPConfig
from vip_tests.workbench.conftest import TIMEOUT_DIALOG, TIMEOUT_IDE_LOAD
from vip_tests.workbench.pages import JupyterLabSession, PositronSession, VSCodeSession

# Import shared steps so pytest-bdd registers them for this module.
# _FILENAME is excluded — it belongs to test_ide_launch and would cause
# session names to be misattributed in logs.
from vip_tests.workbench.test_ide_launch import (  # noqa: F401
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


@scenario("test_ide_extensions.feature", "VS Code has required extensions")
def test_vscode_extensions():
    pass


@scenario("test_ide_extensions.feature", "JupyterLab has required extensions")
def test_jupyterlab_extensions():
    pass


@scenario("test_ide_extensions.feature", "Positron has required extensions")
def test_positron_extensions():
    pass


# ---------------------------------------------------------------------------
# Default extension checks (Posit Workbench integration)
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


# ---------------------------------------------------------------------------
# Admin-configured extension checks
# ---------------------------------------------------------------------------


def _verify_extensions_panel(page: Page, selectors, extension_ids: list[str]) -> None:
    """Open the Extensions sidebar and verify each extension is installed.

    Works for both VS Code and Positron — accepts the page object class
    so Positron can use its own selectors if the UI diverges.
    """
    if not extension_ids:
        return

    # Open Extensions view via keyboard shortcut
    page.keyboard.press("Control+Shift+x")
    extensions_input = page.locator(selectors.EXTENSIONS_SEARCH_INPUT)
    expect(extensions_input).to_be_visible(timeout=TIMEOUT_DIALOG)

    for ext_id in extension_ids:
        extensions_input.fill(f"@installed {ext_id}")
        ext_item = page.locator(selectors.extension_list_item(ext_id))
        expect(ext_item).to_be_visible(timeout=TIMEOUT_IDE_LOAD)

    # Close the Extensions panel to leave the IDE in a clean state
    page.keyboard.press("Control+Shift+x")


@then("all configured VS Code extensions are installed")
def vscode_configured_extensions(page: Page, vip_config: VIPConfig):
    """Verify admin-declared VS Code extensions from [workbench.extensions]."""
    _verify_extensions_panel(page, VSCodeSession, vip_config.workbench.extensions.vscode)


@then("all configured JupyterLab extensions are installed")
def jupyterlab_configured_extensions(page: Page, vip_config: VIPConfig):
    """Verify admin-declared JupyterLab extensions from [workbench.extensions].

    JupyterLab has no universal extensions panel like VS Code. Admin-declared
    extensions are verified by checking the Extension Manager sidebar.
    """
    extension_ids = vip_config.workbench.extensions.jupyterlab
    if not extension_ids:
        return

    # Guard: Extension Manager may be disabled by the admin
    ext_tab = page.locator(JupyterLabSession.EXTENSION_MANAGER_TAB)
    if ext_tab.count() == 0:
        pytest.skip(
            "JupyterLab Extension Manager is not available in this deployment. "
            "Cannot verify configured extensions."
        )

    ext_tab.click(timeout=TIMEOUT_DIALOG)
    search_input = page.locator(JupyterLabSession.EXTENSION_SEARCH_INPUT)
    expect(search_input).to_be_visible(timeout=TIMEOUT_DIALOG)

    for ext_id in extension_ids:
        search_input.fill(ext_id)
        ext_item = page.locator(JupyterLabSession.installed_extension_item(ext_id))
        expect(ext_item).to_be_visible(timeout=TIMEOUT_IDE_LOAD)

    search_input.fill("")


@then("all configured Positron extensions are installed")
def positron_configured_extensions(page: Page, vip_config: VIPConfig):
    """Verify admin-declared Positron extensions from [workbench.extensions]."""
    _verify_extensions_panel(page, PositronSession, vip_config.workbench.extensions.positron)
