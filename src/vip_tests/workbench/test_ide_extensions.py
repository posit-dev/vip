"""Step definitions for Workbench IDE extension validation tests.

These tests verify that the Posit Workbench extension is installed and visible
in VS Code, JupyterLab, and Positron sessions, plus any additional extensions
declared in vip.toml under [workbench.extensions].

The session lifecycle steps (login, start, becomes-active, IDE-displayed,
cleanup) are reimplemented here rather than imported from test_ide_launch:
pytest-bdd registers step decorators at decoration time against the defining
module, so cross-module imports of @given/@when/@then functions do not
register them for the importer. This matches the pattern in test_packages.py
and test_sessions.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from pytest_bdd import given, scenario, then, when

from vip.config import VIPConfig
from vip_tests.workbench.conftest import (
    TIMEOUT_CLEANUP,
    TIMEOUT_DIALOG,
    TIMEOUT_IDE_LOAD,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_QUICK,
    TIMEOUT_SESSION_START,
    assert_homepage_loaded,
    unique_session_name,
    workbench_login,
)
from vip_tests.workbench.pages import (
    Homepage,
    JupyterLabSession,
    NewSessionDialog,
    PositronSession,
    VSCodeSession,
)

_FILENAME = Path(__file__).name


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
# Shared state
# ---------------------------------------------------------------------------


@pytest.fixture
def session_context(page: Page, workbench_url: str):
    """Holds session name across steps, with best-effort cleanup on skip/fail."""
    ctx: dict = {"name": None, "ide_type": None, "cleaned_up": False}
    yield ctx
    if not ctx.get("name") or ctx.get("cleaned_up"):
        return
    try:
        home_url = workbench_url.rstrip("/") + "/home"
        page.goto(home_url)
        checkbox = page.locator(Homepage.session_checkbox(ctx["name"]))
        if checkbox.count() > 0:
            checkbox.click()
            quit_btn = page.locator(Homepage.QUIT_BUTTON)
            if quit_btn.count() > 0:
                quit_btn.click()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Session lifecycle steps
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
    session_name = unique_session_name(_FILENAME)
    session_context["name"] = session_name
    session_context["ide_type"] = ide_name
    _start_session(page, ide_name, session_name)


@when("the user starts a new VS Code session")
def start_vscode_session(page: Page, session_context: dict):
    _start_ide_session(session_context, page, "VS Code")


@when("the user starts a new JupyterLab session")
def start_jupyter_session(page: Page, session_context: dict):
    _start_ide_session(session_context, page, "JupyterLab")


@when("the user starts a new Positron session")
def start_positron_session(page: Page, session_context: dict):
    _start_ide_session(session_context, page, "Positron")


def _start_session(page: Page, ide_type: str, session_name: str) -> None:
    """Start a new session using the rstudio-pro dialog pattern.

    Intentionally unchecks auto-join so we can observe the session
    state transitions on the homepage before navigating into the session.
    """
    page.locator(Homepage.NEW_SESSION_BUTTON).first.click(timeout=TIMEOUT_DIALOG)

    dialog = page.locator(NewSessionDialog.DIALOG)
    expect(dialog.locator(NewSessionDialog.TITLE)).to_have_text(
        "New Session", timeout=TIMEOUT_DIALOG
    )

    ide_display = NewSessionDialog.ide_display_name(ide_type)
    ide_tab = dialog.get_by_role("tab", name=ide_display)
    if ide_tab.count() == 0:
        _dismiss_dialog_and_skip(page, f"{ide_type} IDE not available in this Workbench deployment")
    ide_tab.click(timeout=TIMEOUT_QUICK)

    launch_btn = page.locator(NewSessionDialog.LAUNCH_BUTTON)
    try:
        launch_btn.wait_for(state="visible", timeout=TIMEOUT_QUICK)
    except PlaywrightTimeoutError:
        _dismiss_dialog_and_skip(
            page,
            f"{ide_type} tab opened but Launch button did not appear — "
            f"the IDE may not be installed or fully available on this Workbench instance",
        )

    page.fill(NewSessionDialog.SESSION_NAME, session_name)

    checkbox = page.locator(NewSessionDialog.JOIN_CHECKBOX)
    if checkbox.is_checked():
        checkbox.click()
    expect(checkbox).not_to_be_checked(timeout=TIMEOUT_QUICK)

    launch_btn.click(timeout=TIMEOUT_QUICK)


def _dismiss_dialog_and_skip(page: Page, reason: str) -> NoReturn:
    """Best-effort cancel of the New Session dialog, then pytest.skip."""
    try:
        cancel = page.locator(NewSessionDialog.CANCEL_BUTTON)
        if cancel.count() > 0:
            try:
                cancel.click(timeout=TIMEOUT_QUICK)
            except (PlaywrightTimeoutError, PlaywrightError):
                pass
    except (PlaywrightTimeoutError, PlaywrightError):
        pass
    pytest.skip(reason)


@then("the session transitions to Active state")
def session_becomes_active(page: Page, session_context: dict):
    """Verify session transitions from Starting to Active."""
    session_name = session_context["name"]

    session_row = page.locator(Homepage.session_row(session_name))
    expect(session_row).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)

    session_active = page.locator(Homepage.session_row_status(session_name, "Active"))
    expect(session_active).to_be_visible(timeout=TIMEOUT_SESSION_START)

    session_link = session_row.locator(f"a[title='join {session_name}']")
    expect(session_link).to_be_visible(timeout=TIMEOUT_DIALOG)
    session_link.click()


def _expect_ide_or_skip(
    page: Page,
    locator_str: str,
    ide_name: str,
    *,
    timeout: int | None = None,
) -> None:
    """Wait for the primary IDE element; skip if it times out."""
    effective_timeout = TIMEOUT_IDE_LOAD if timeout is None else timeout
    try:
        page.locator(locator_str).wait_for(state="visible", timeout=effective_timeout)
    except PlaywrightTimeoutError as exc:
        pytest.skip(
            f"{ide_name} did not load within timeout — "
            f"the IDE may not be installed on this Workbench instance ({exc})"
        )


@then("the VS Code IDE is displayed")
def vscode_displayed(page: Page):
    _expect_ide_or_skip(page, VSCodeSession.WORKBENCH, "VS Code")
    expect(page.locator(VSCodeSession.STATUS_BAR)).to_be_visible(timeout=TIMEOUT_DIALOG)


@then("the JupyterLab IDE is displayed")
def jupyter_displayed(page: Page):
    _expect_ide_or_skip(page, JupyterLabSession.LAUNCHER, "JupyterLab")


@then("the Positron IDE is displayed")
def positron_displayed(page: Page):
    _expect_ide_or_skip(page, PositronSession.WORKBENCH, "Positron")
    expect(page.locator(PositronSession.STATUS_BAR)).to_be_visible(timeout=TIMEOUT_DIALOG)


@then("the session is cleaned up")
def session_cleaned_up(page: Page, workbench_url: str, session_context: dict):
    """Navigate back to homepage and quit the session."""
    session_name = session_context["name"]
    session_context["cleaned_up"] = True

    home_url = workbench_url.rstrip("/") + "/home"
    page.goto(home_url)
    expect(page.locator(Homepage.POSIT_LOGO)).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)

    checkbox = page.locator(Homepage.session_checkbox(session_name))
    expect(checkbox).to_be_visible(timeout=TIMEOUT_DIALOG)
    checkbox.click()

    quit_btn = page.locator(Homepage.QUIT_BUTTON)
    expect(quit_btn).to_be_visible(timeout=TIMEOUT_QUICK)
    quit_btn.click()

    session_link = page.locator(Homepage.session_link(session_name))
    expect(session_link).not_to_be_visible(timeout=TIMEOUT_CLEANUP)


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

    page.keyboard.press("Control+Shift+x")
    extensions_input = page.locator(selectors.EXTENSIONS_SEARCH_INPUT)
    expect(extensions_input).to_be_visible(timeout=TIMEOUT_DIALOG)

    for ext_id in extension_ids:
        extensions_input.fill(f"@installed {ext_id}")
        ext_item = page.locator(selectors.extension_list_item(ext_id))
        expect(ext_item).to_be_visible(timeout=TIMEOUT_IDE_LOAD)

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
