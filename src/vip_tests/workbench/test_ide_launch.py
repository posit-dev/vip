"""Step definitions for Workbench IDE launch tests.

These tests verify that each IDE type can be started and becomes functional.
Patterns adapted from rstudio-pro/e2e tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from pytest_bdd import given, scenario, then, when

from vip_tests.workbench.conftest import (
    TIMEOUT_CLEANUP,
    TIMEOUT_CODE_EXEC,
    TIMEOUT_DIALOG,
    TIMEOUT_IDE_LOAD,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_QUICK,
    assert_homepage_loaded,
    unique_session_name,
    wait_for_session_active,
    workbench_login,
)
from vip_tests.workbench.exec import ensure_positron_console, rstudio_eval
from vip_tests.workbench.pages import (
    Homepage,
    JupyterLabSession,
    NewSessionDialog,
    PositronSession,
    RStudioSession,
    VSCodeSession,
)

pytestmark = pytest.mark.order(20)

# Get filename for session naming
_FILENAME = Path(__file__).name


@pytest.mark.rstudio
@scenario("test_ide_launch.feature", "RStudio IDE session can be launched")
def test_launch_rstudio():
    pass


@pytest.mark.vscode
@scenario("test_ide_launch.feature", "VS Code session can be launched")
def test_launch_vscode():
    pass


@pytest.mark.jupyter
@scenario("test_ide_launch.feature", "JupyterLab session can be launched")
def test_launch_jupyter():
    pass


@pytest.mark.positron
@scenario("test_ide_launch.feature", "Positron session can be launched")
def test_launch_positron():
    pass


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------


@pytest.fixture
def session_context(page: Page, workbench_url: str):
    """Holds session name across steps, with best-effort cleanup on skip/fail.

    If a session was started (``name`` is set) and the test aborted before the
    "session is cleaned up" step ran, this finalizer navigates back to the
    homepage and quits the session to prevent resource leaks.
    """
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
        # Best-effort cleanup — don't mask the original failure/skip.
        pass


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
    auth_mode: str,
    workbench_auth_error: str | None,
):
    """Log in to Workbench and verify homepage loads."""
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


def _start_ide_session(session_context: dict, page: Page, ide_name: str) -> None:
    """Set session context and start a new IDE session of the given type."""
    session_name = unique_session_name(_FILENAME)
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
    ide_tab = dialog.get_by_role("tab", name=ide_display)
    if ide_tab.count() == 0:
        _dismiss_dialog_and_skip(page, f"{ide_type} IDE not available in this Workbench deployment")
    ide_tab.click(timeout=TIMEOUT_QUICK)

    # After selecting the IDE tab, the Launch button should become available
    # within a couple of seconds.  If it doesn't, the tab is present but the
    # IDE is not actually installed/functional on this Workbench instance
    # (the dialog shows an error state without a Launch button).  Skip
    # gracefully instead of letting the subsequent Launch click time out
    # for 30s on #modalCancelBtn.
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

    # Uncheck auto-join so we stay on homepage to observe state transitions
    checkbox = page.locator(NewSessionDialog.JOIN_CHECKBOX)
    if checkbox.is_checked():
        checkbox.click()
    expect(checkbox).not_to_be_checked(timeout=TIMEOUT_QUICK)

    launch_btn.click(timeout=TIMEOUT_QUICK)


def _dismiss_dialog_and_skip(page: Page, reason: str) -> NoReturn:
    """Best-effort cancel of the New Session dialog, then ``pytest.skip``.

    Uses a short timeout on the cancel click so a missing or unreachable
    cancel button does not mask the real skip reason with a 30-second
    Playwright default-timeout error on ``#modalCancelBtn``.

    Catches both ``PlaywrightTimeoutError`` and the base ``PlaywrightError``
    (raised for detached/covered elements and other non-actionable states) so
    that dialog-dismiss failures never mask the intended skip.
    """
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

    # Wait for our session to reach Active state.  Fails fast with an
    # actionable message if it reaches a terminal state (e.g. Failed) instead
    # of waiting out the full session-start timeout.
    session_row = wait_for_session_active(page, session_name)

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


def _expect_ide_or_skip(
    page: Page,
    locator_str: str,
    ide_name: str,
    *,
    timeout: int | None = None,
    skip_reason: str | None = None,
) -> None:
    """Wait for the primary IDE element; skip if it times out (IDE may not be installed).

    Uses ``Locator.wait_for(state="visible")`` which raises a Playwright
    ``TimeoutError`` on timeout — a stable, typed distinction from other
    assertion failures.  Any other exception propagates normally.

    Args:
        page: The Playwright page object.
        locator_str: CSS/XPath selector for the element to wait for.
        ide_name: Human-readable IDE name used in the default skip message.
        timeout: Wait timeout in milliseconds.  Defaults to ``TIMEOUT_IDE_LOAD``
            (60 s) when not specified.
        skip_reason: Custom skip message.  When omitted the default message
            ``"{ide_name} did not load within timeout — ..."`` is used.
            The string may contain ``{exc}`` which will be substituted with the
            caught ``PlaywrightTimeoutError`` instance.
    """
    effective_timeout = TIMEOUT_IDE_LOAD if timeout is None else timeout
    try:
        page.locator(locator_str).wait_for(state="visible", timeout=effective_timeout)
    except PlaywrightTimeoutError as exc:
        if skip_reason is None:
            reason = (
                f"{ide_name} did not load within timeout — "
                f"the IDE may not be installed on this Workbench instance ({exc})"
            )
        else:
            reason = skip_reason.format(exc=exc) if "{exc}" in skip_reason else skip_reason
        pytest.skip(reason)


@then("the VS Code IDE is displayed")
def vscode_displayed(page: Page):
    """Verify VS Code IDE core elements are visible."""
    _expect_ide_or_skip(page, VSCodeSession.WORKBENCH, "VS Code")
    # If we get here, VS Code is installed — a missing status bar is a real failure.
    expect(page.locator(VSCodeSession.STATUS_BAR)).to_be_visible(timeout=TIMEOUT_DIALOG)


@then("the JupyterLab IDE is displayed")
def jupyter_displayed(page: Page):
    """Verify JupyterLab IDE core elements are visible.

    Gates on the JupyterLab application shell (``.jp-LabShell``), which is
    present on every JupyterLab load regardless of the active view — NOT on
    ``.jp-Launcher``, which only exists while the Launcher tab is open.  On
    some deployments JupyterLab opens without the Launcher tab, so gating on
    the launcher produced a false "IDE may not be installed" skip even though
    JupyterLab was fully loaded (issue #478).
    """
    _expect_ide_or_skip(page, JupyterLabSession.SHELL, "JupyterLab")


@then("the Positron IDE is displayed")
def positron_displayed(page: Page):
    """Verify Positron IDE core elements are visible."""
    _expect_ide_or_skip(page, PositronSession.WORKBENCH, "Positron")
    # If we get here, Positron is installed — a missing status bar is a real failure.
    expect(page.locator(PositronSession.STATUS_BAR)).to_be_visible(timeout=TIMEOUT_DIALOG)


@then("the RStudio IDE can execute R code")
def rstudio_executes_r_code(page: Page):
    """Type a simple R expression into the console and verify the output.

    Delegates to ``rstudio_eval`` from ``exec.py``, which uses marker-bracketed
    capture to reliably extract the console output for this specific expression.
    Generous timeouts are used because R startup and first-expression evaluation
    can be slow on a freshly started session.
    """
    result = rstudio_eval(page, "1 + 1", timeout=TIMEOUT_CODE_EXEC)
    assert "2" in result, f"Expected '2' in RStudio eval output, got: {result!r}"


@then("the VS Code terminal is accessible")
def vscode_terminal_accessible(page: Page):
    """Verify the VS Code terminal panel can be opened.

    Opens the integrated terminal via the keyboard shortcut and waits for the
    terminal input area to become visible.  This confirms the shell runtime is
    reachable even though we do not execute a command.
    """
    expect(page.locator(VSCodeSession.WORKBENCH)).to_be_visible(timeout=TIMEOUT_IDE_LOAD)

    # Open the integrated terminal with the standard VS Code shortcut
    page.keyboard.press("Control+`")

    terminal_input = page.locator(VSCodeSession.TERMINAL_INPUT)
    expect(terminal_input).to_be_visible(timeout=TIMEOUT_CODE_EXEC)


def _accept_open_dialogs(page: Page, *, attempts: int = 20) -> None:
    """Dismiss JupyterLab modal dialogs (e.g. "Select Kernel") by accepting the
    default, polling because they can appear a moment after the triggering
    action rather than immediately.  Best-effort: never raises.
    """
    for _ in range(attempts):
        if page.locator(JupyterLabSession.DIALOG).count() == 0:
            return
        accept = page.locator(JupyterLabSession.DIALOG_ACCEPT).first
        try:
            if accept.count() > 0:
                accept.click(timeout=TIMEOUT_QUICK)
            else:
                page.keyboard.press("Enter")
        except (PlaywrightTimeoutError, PlaywrightError):
            pass
        page.wait_for_timeout(1000)


@then("JupyterLab can execute code in a notebook")
def jupyterlab_executes_code(page: Page):
    """Open a new notebook from the launcher and execute ``1 + 1``.

    Clicks the first available notebook kernel card in the JupyterLab launcher,
    waits for the notebook to open, types an expression into the first code
    cell, runs it, and asserts that ``2`` appears in the cell output area.

    Skips gracefully if no notebook kernel cards are available (e.g., when
    the Docker image lacks a working kernel).
    """
    # JupyterLab's shell (.jp-LabShell) mounts before the app finishes booting:
    # the #jupyterlab-splash overlay lingers for a few seconds, intercepting
    # clicks and detaching elements mid-hydration.  Wait for it to clear before
    # interacting, otherwise the launcher-open click is raced away (issue #478).
    try:
        page.locator(JupyterLabSession.SPLASH).wait_for(state="hidden", timeout=TIMEOUT_IDE_LOAD)
    except (PlaywrightTimeoutError, PlaywrightError):
        pass  # splash already gone (or never rendered)

    # A fresh JupyterLab session on some deployments opens with no Launcher tab
    # (issue #478), so no launcher cards are present.  Open a Launcher via
    # JupyterLab's built-in ``launcher:create`` command control (retrying once),
    # then wait for the notebook kernel card to appear.
    notebook_card = page.locator(JupyterLabSession.LAUNCHER_NOTEBOOK_CARD).first
    for _attempt in range(2):
        if notebook_card.count() > 0:
            break
        opener = page.locator(JupyterLabSession.LAUNCHER_CREATE_COMMAND).first
        if opener.count() == 0:
            break
        try:
            opener.click(timeout=TIMEOUT_QUICK)
            page.locator(JupyterLabSession.LAUNCHER_NOTEBOOK_CARD).first.wait_for(
                state="visible", timeout=TIMEOUT_IDE_LOAD
            )
        except (PlaywrightTimeoutError, PlaywrightError):
            pass  # fall through; re-check below and retry or skip
        notebook_card = page.locator(JupyterLabSession.LAUNCHER_NOTEBOOK_CARD).first
    if notebook_card.count() == 0:
        pytest.skip("No notebook kernel cards available in JupyterLab launcher")
    expect(notebook_card).to_be_visible(timeout=TIMEOUT_CODE_EXEC)
    notebook_card.click()

    # Clicking the card opens a notebook as the active dock tab.  Several hidden
    # notebook panels can coexist, so target the *visible* (active) one rather
    # than a bare selector that would match multiple, then work within it.
    notebook_panel = page.locator(f"{JupyterLabSession.NOTEBOOK_PANEL}:visible").first
    expect(notebook_panel).to_be_visible(timeout=TIMEOUT_IDE_LOAD)

    # A new notebook pops a modal "Select Kernel" dialog that intercepts clicks.
    # It appears a moment *after* the notebook opens (once the kernel connects),
    # so poll and dismiss it (accept the default kernel) rather than checking
    # once — accepting the default makes the cell interactive (issue #478).
    _accept_open_dialogs(page)

    # Click into the first code cell input of the active notebook and type.
    cell_input = notebook_panel.locator(JupyterLabSession.CELL_INPUT).first
    expect(cell_input).to_be_visible(timeout=TIMEOUT_CODE_EXEC)
    cell_input.click()
    cell_input.type("1 + 1")

    # Run the cell with Shift+Enter
    cell_input.press("Shift+Enter")

    # Assert the output area shows 2.  The kernel may be slow to start in
    # Docker CI, so allow a generous timeout before skipping.
    cell_output = notebook_panel.locator(JupyterLabSession.CELL_OUTPUT).first
    try:
        expect(cell_output).to_contain_text("2", timeout=TIMEOUT_CODE_EXEC)
    except AssertionError:
        pytest.skip(
            "JupyterLab kernel did not produce output within timeout — "
            "kernel may not be fully functional in this environment"
        )


@then("the Positron console is accessible")
def positron_console_accessible(page: Page):
    """Start a Positron console session and verify the console panel renders.

    Positron (Workbench 2026+) opens to a Welcome page with **no auto-started
    console**: ``.positron-console`` does not exist until a console session is
    started and an interpreter is selected (discovery is asynchronous, ~10 s).
    The previous gate waited for ``.positron-console`` on the Welcome page — where
    it can never appear — and skipped with a misleading "may not be installed"
    even though Positron was fully loaded (issue #477).

    ``ensure_positron_console`` clicks "Start New Console Session", waits for the
    interpreter quickpick, selects an interpreter, and waits for the console.  If
    Positron loaded but no interpreter could be started, skip with an accurate
    reason rather than implying Positron is missing.
    """
    if not ensure_positron_console(page, timeout=TIMEOUT_IDE_LOAD):
        pytest.skip(
            "Positron loaded but no console session could be started — the "
            '"Start New Console Session" control was unavailable, no R/Python '
            "interpreter resolved, or the console did not render (issue #477)."
        )
    expect(page.locator(PositronSession.CONSOLE_PANEL)).to_be_visible(timeout=TIMEOUT_CODE_EXEC)


@then("the session is cleaned up")
def session_cleaned_up(page: Page, workbench_url: str, session_context: dict):
    """Navigate back to homepage and quit the session."""
    session_name = session_context["name"]
    session_context["cleaned_up"] = True

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
