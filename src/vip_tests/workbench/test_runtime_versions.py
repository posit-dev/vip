"""Step definitions for Workbench runtime version checks."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from pytest_bdd import given, scenario, then, when

from vip_tests.workbench.conftest import (
    TIMEOUT_CLEANUP,
    TIMEOUT_DIALOG,
    TIMEOUT_IDE_LOAD,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_QUICK,
    assert_homepage_loaded,
    unique_session_name,
    wait_for_session_active,
    workbench_login,
)
from vip_tests.workbench.pages import (
    ConsolePaneSelectors,
    Homepage,
    NewSessionDialog,
    RStudioSession,
)

pytestmark = pytest.mark.order(50)

_FILENAME = Path(__file__).name


@scenario(
    "test_runtime_versions.feature",
    "Launched RStudio session reports an expected R version",
)
def test_r_version_in_session():
    pass


# ---------------------------------------------------------------------------
# Shared login step (reuses the exact step text from other workbench tests)
# ---------------------------------------------------------------------------


@given("the user is logged in to Workbench")
def user_logged_in(
    page: Page,
    workbench_url: str,
    test_username: str,
    test_password: str,
    auth_provider: str,
    interactive_auth: bool,
    auth_mode: str,
    workbench_auth_error: str | None,
):
    workbench_login(
        page,
        workbench_url,
        test_username,
        test_password,
        auth_provider,
        interactive_auth,
        auth_mode=auth_mode,
        workbench_auth_error=workbench_auth_error,
    )
    assert_homepage_loaded(page)


# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------


@given("expected R versions are specified in vip.toml")
def r_versions_specified(expected_r_versions):
    if not expected_r_versions:
        pytest.skip("No expected R versions specified in vip.toml [runtimes]")


def _dismiss_dialog(page: Page) -> None:
    """Best-effort close of the New Session dialog.

    The legacy ``#modalCancelBtn`` (``NewSessionDialog.CANCEL_BUTTON``) is not
    present/actionable in the current Workbench New Session dialog, so a direct
    click hangs until timeout.  Try the cancel button briefly, fall back to
    pressing Escape, and never let dialog teardown fail an assertion-focused
    test.  Mirrors the defensive dismiss in ``test_ide_launch._dismiss_dialog_and_skip``.
    """
    dialog = page.locator(NewSessionDialog.DIALOG)
    try:
        cancel = page.locator(NewSessionDialog.CANCEL_BUTTON)
        if cancel.count() > 0:
            cancel.click(timeout=TIMEOUT_QUICK)
    except (PlaywrightTimeoutError, PlaywrightError):
        pass
    try:
        if dialog.count() > 0 and dialog.first.is_visible():
            page.keyboard.press("Escape")
    except (PlaywrightTimeoutError, PlaywrightError):
        pass
    try:
        expect(dialog).not_to_be_visible(timeout=TIMEOUT_QUICK)
    except (AssertionError, PlaywrightTimeoutError, PlaywrightError):
        pass


def _open_dialog_with_rstudio_tab(page: Page):
    """Open the New Session dialog and activate the RStudio Pro IDE tab.

    The current Workbench New Session dialog is tabbed per IDE and defaults to
    Positron.  Both the R/Python version selectors and an RStudio session
    require the RStudio Pro tab to be active, so select it explicitly rather
    than relying on the dialog's default IDE.  Skips gracefully when RStudio Pro
    is not offered or its Launch control never appears.  Mirrors the tab
    selection in ``test_ide_launch._start_session``.
    """
    page.locator(Homepage.NEW_SESSION_BUTTON).first.click(timeout=TIMEOUT_DIALOG)
    dialog = page.locator(NewSessionDialog.DIALOG)
    # Assert the New Session dialog title rather than relying on the broad
    # ``[role='dialog']`` selector, which can match unrelated dialogs.  Mirrors
    # the title assertion in ``test_ide_launch._start_session``.
    expect(dialog.locator(NewSessionDialog.TITLE)).to_have_text(
        "New Session", timeout=TIMEOUT_DIALOG
    )

    ide_display = NewSessionDialog.ide_display_name("RStudio")  # "RStudio Pro"
    ide_tab = dialog.get_by_role("tab", name=ide_display)
    if ide_tab.count() == 0:
        _dismiss_dialog(page)
        pytest.skip(f"{ide_display} IDE not available in this Workbench deployment")
    ide_tab.click(timeout=TIMEOUT_QUICK)

    # The Launch button only appears once the selected tab's content is ready.
    # If it never shows, the tab exists but the IDE is not functional here.
    try:
        dialog.locator(NewSessionDialog.LAUNCH_BUTTON).wait_for(
            state="visible", timeout=TIMEOUT_QUICK
        )
    except PlaywrightTimeoutError:
        _dismiss_dialog(page)
        pytest.skip(
            f"{ide_display} tab opened but Launch button did not appear — "
            "the IDE may not be installed or available on this Workbench instance"
        )
    return dialog


# ---------------------------------------------------------------------------
# In-session scenario: launch RStudio with a specific R version
# ---------------------------------------------------------------------------


@pytest.fixture
def session_context(page: Page, workbench_url: str):
    """Holds session state across steps with best-effort cleanup."""
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


@when(
    "the user starts a new RStudio session",
    target_fixture="session_context",
)
def start_rstudio_session(
    page: Page,
    session_context: dict,
    workbench_url: str,
    expected_r_versions: list[str],
):
    session_name = unique_session_name(_FILENAME)
    session_context["name"] = session_name
    session_context["ide_type"] = "RStudio"
    session_context["expected_r_version"] = expected_r_versions[0]

    # Select the RStudio Pro IDE tab so an RStudio session launches.  Without
    # this the dialog launches its default IDE (Positron on current Workbench),
    # and the later ``#rstudio_container`` assertion times out.
    dialog = _open_dialog_with_rstudio_tab(page)

    page.fill(NewSessionDialog.SESSION_NAME, session_name)

    join_checkbox = page.locator(NewSessionDialog.JOIN_CHECKBOX)
    if join_checkbox.is_checked():
        join_checkbox.click()
    expect(join_checkbox).not_to_be_checked(timeout=TIMEOUT_QUICK)

    dialog.locator(NewSessionDialog.LAUNCH_BUTTON).click(timeout=TIMEOUT_QUICK)
    return session_context


@then("the session transitions to Active state")
def session_becomes_active(page: Page, session_context: dict):
    session_name = session_context["name"]
    session_row = wait_for_session_active(page, session_name)
    session_link = session_row.locator(f"a[title='join {session_name}']")
    expect(session_link).to_be_visible(timeout=TIMEOUT_DIALOG)
    session_link.click()


@then("the RStudio console reports the expected R version")
def rstudio_reports_r_version(page: Page, session_context: dict):
    expected_version = session_context["expected_r_version"]

    expect(page.locator(RStudioSession.CONTAINER)).to_be_visible(timeout=TIMEOUT_IDE_LOAD)

    console_input = page.locator(ConsolePaneSelectors.INPUT)
    expect(console_input).to_be_visible(timeout=TIMEOUT_IDE_LOAD)
    console_input.click()
    console_input.type("R.version$major")
    console_input.press("Enter")

    console_output = page.locator(ConsolePaneSelectors.OUTPUT)
    major = expected_version.split(".")[0]
    expect(console_output).to_contain_text(f'[1] "{major}"', timeout=TIMEOUT_IDE_LOAD)


@then("the session is cleaned up")
def session_cleaned_up(page: Page, workbench_url: str, session_context: dict):
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
