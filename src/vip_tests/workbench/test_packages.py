"""Step definitions for Workbench package source checks."""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import given, scenario, then, when

from vip_tests.workbench.conftest import (
    TIMEOUT_DIALOG,
    TIMEOUT_IDE_LOAD,
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

_FILENAME = Path(__file__).name

# Time (ms) to wait for the R console input to become visible after IDE load
_TIMEOUT_CONSOLE_READY = 30_000
# Time (ms) to wait for console output to appear after pressing Enter
_TIMEOUT_R_OUTPUT = 15_000


@scenario("test_packages.feature", "R repos.conf points to the expected repository")
def test_r_repo_configured():
    pass


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


def _start_session(page: Page, session_name: str) -> None:
    """Start a new RStudio session with auto-join unchecked."""
    page.locator(Homepage.NEW_SESSION_BUTTON).first.click(timeout=TIMEOUT_DIALOG)

    dialog = page.locator(NewSessionDialog.DIALOG)
    expect(dialog.locator(NewSessionDialog.TITLE)).to_have_text(
        "New Session", timeout=TIMEOUT_DIALOG
    )

    ide_display = NewSessionDialog.ide_display_name("RStudio")
    dialog.get_by_role("tab", name=ide_display).click(timeout=TIMEOUT_QUICK)

    page.fill(NewSessionDialog.SESSION_NAME, session_name)

    checkbox = page.locator(NewSessionDialog.JOIN_CHECKBOX)
    if checkbox.is_checked():
        checkbox.click()
    expect(checkbox).not_to_be_checked(timeout=TIMEOUT_QUICK)

    page.locator(NewSessionDialog.LAUNCH_BUTTON).click(timeout=TIMEOUT_QUICK)


def _wait_for_active_and_join(page: Page, session_name: str) -> None:
    """Wait for the session to reach Active state, then navigate into it.

    Fails fast with an actionable message if the session reaches a terminal
    state (e.g. Failed) rather than waiting out the full session-start timeout.
    """
    session_row = wait_for_session_active(page, session_name)

    session_link = session_row.locator(f"a[title='join {session_name}']")
    expect(session_link).to_be_visible(timeout=TIMEOUT_DIALOG)
    session_link.click()


def _execute_r_command(page: Page, command: str) -> str:
    """Type an R command into the RStudio console and return the output pane text.

    Waits for the console input to be ready, types the command, presses Enter,
    and captures the full console output pane text for the caller to parse.
    """
    console_input = page.locator(ConsolePaneSelectors.INPUT)
    expect(console_input).to_be_visible(timeout=_TIMEOUT_CONSOLE_READY)

    console_input.click()
    # The console input is an ACE editor <div>, not an <input>, so fill()
    # doesn't work.  Select-all + delete to clear any previous content.
    # ControlOrMeta maps select-all to Cmd+A on macOS, where Ctrl+A is "go to
    # line start" and would leave previous content in place.
    page.keyboard.press("ControlOrMeta+a")
    page.keyboard.press("Backspace")
    console_input.type(command)
    console_input.press("Enter")

    # Brief pause to let R evaluate before reading the output pane
    time.sleep(1)

    output_el = page.locator(ConsolePaneSelectors.OUTPUT_ELEMENT)
    expect(output_el).to_be_visible(timeout=_TIMEOUT_R_OUTPUT)
    return output_el.inner_text()


@when(
    "I check R repository configuration in an RStudio session",
    target_fixture="repo_check_url",
)
def check_r_repos(page: Page, workbench_url: str):
    """Start an RStudio session, run getOption('repos'), and return found URLs."""
    session_name = unique_session_name(_FILENAME)

    _start_session(page, session_name)
    _wait_for_active_and_join(page, session_name)

    # Wait for RStudio to be fully loaded before interacting with the console
    expect(page.locator(RStudioSession.LOGO)).to_be_visible(timeout=TIMEOUT_IDE_LOAD)
    expect(page.locator(RStudioSession.CONTAINER)).to_be_visible(timeout=TIMEOUT_DIALOG)

    output = _execute_r_command(page, "getOption('repos')")

    repo_urls = re.findall(r"https?://[^\s<>\"']+", output)

    if not repo_urls:
        pytest.skip(
            "getOption('repos') returned no URLs. "
            "Verify that R is available and repos.conf is configured in this Workbench deployment."
        )

    return repo_urls


@then("the expected package repository URL is present")
def repo_url_present(repo_check_url, vip_config):
    if not vip_config.package_manager.is_configured:
        pytest.skip("Package Manager URL is not configured in vip.toml; cannot verify R repos")
    expected = vip_config.package_manager.url.rstrip("/")
    found = any(u.rstrip("/") == expected or u.startswith(expected + "/") for u in repo_check_url)
    assert found, (
        f"Package Manager URL {expected!r} not found in R repository configuration. "
        f"Found URLs: {repo_check_url[:10]}"
    )
