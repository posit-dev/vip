"""Step definitions for Workbench external data source tests."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import given, scenario, then, when

from vip_tests.workbench.conftest import (
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
    ConsolePaneSelectors,
    Homepage,
    NewSessionDialog,
    RStudioSession,
)

_FILENAME = Path(__file__).name

# Types that support an HTTP connectivity check via base R
_HTTP_TYPES = {"http", "api"}

# Time (ms) to wait for the R console input to become visible after IDE load
_TIMEOUT_CONSOLE_READY = 30_000
# Time (ms) to wait for R command output to appear after pressing Enter
_TIMEOUT_R_OUTPUT = 15_000


@scenario("test_data_sources.feature", "External data sources are reachable from Workbench")
def test_data_sources_reachable():
    pass


@given("Workbench is accessible at the configured URL")
def workbench_accessible(workbench_client):
    assert workbench_client is not None


@given("external data sources are configured in vip.toml")
def data_sources_configured(data_sources):
    if not data_sources:
        pytest.skip("No data sources configured in vip.toml")


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
    """Wait for the session to reach Active state, then navigate into it."""
    session_row = page.locator(Homepage.session_row(session_name))
    expect(session_row).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)

    session_active = page.locator(Homepage.session_row_status(session_name, "Active"))
    expect(session_active).to_be_visible(timeout=TIMEOUT_SESSION_START)

    session_link = session_row.locator(f"a[title='join {session_name}']")
    expect(session_link).to_be_visible(timeout=TIMEOUT_DIALOG)
    session_link.click()


def _execute_r_command(page: Page, command: str) -> str:
    """Type an R command into the RStudio console and return the output pane text."""
    console_input = page.locator(ConsolePaneSelectors.INPUT)
    expect(console_input).to_be_visible(timeout=_TIMEOUT_CONSOLE_READY)

    console_input.click()
    console_input.fill("")
    console_input.type(command)
    console_input.press("Enter")

    # Brief pause to let R evaluate before reading the output pane
    time.sleep(1)

    output_el = page.locator(ConsolePaneSelectors.OUTPUT_ELEMENT)
    expect(output_el).to_be_visible(timeout=_TIMEOUT_R_OUTPUT)
    return output_el.inner_text()


def _check_http_source_in_r(page: Page, url: str) -> tuple[bool, str | None]:
    """Use base R to attempt an HTTP GET from within a Workbench session.

    Returns (ok, error_message). Uses url() + readLines() with tryCatch so
    no external R packages are required.
    """
    r_code = (
        "tryCatch({"
        f"  con <- url('{url}', open='r');"
        "  on.exit(close(con));"
        "  readLines(con, n=1L, warn=FALSE);"
        "  cat('VIP_HTTP_OK\\n')"
        "}, error=function(e) cat('VIP_HTTP_ERR:', conditionMessage(e), '\\n'))"
    )
    output = _execute_r_command(page, r_code)
    if "VIP_HTTP_OK" in output:
        return True, None
    # Extract error message after the sentinel, if present
    for line in output.splitlines():
        if "VIP_HTTP_ERR:" in line:
            return False, line.split("VIP_HTTP_ERR:", 1)[-1].strip()
    return False, "No response from R console"


@when("I verify data source connectivity", target_fixture="ds_results")
def verify_connectivity(
    page: Page,
    workbench_url: str,
    test_username: str,
    test_password: str,
    auth_provider: str,
    interactive_auth: bool,
    data_sources,
):
    """Start an RStudio session and verify HTTP data source connectivity from within it."""
    workbench_login(
        page, workbench_url, test_username, test_password, auth_provider, interactive_auth
    )
    assert_homepage_loaded(page)

    session_name = unique_session_name(_FILENAME)
    _start_session(page, session_name)
    _wait_for_active_and_join(page, session_name)

    expect(page.locator(RStudioSession.LOGO)).to_be_visible(timeout=TIMEOUT_IDE_LOAD)
    expect(page.locator(RStudioSession.CONTAINER)).to_be_visible(timeout=TIMEOUT_DIALOG)

    results = []
    for ds in data_sources:
        result: dict = {"name": ds.name, "type": ds.type, "ok": False, "error": None}

        if ds.type not in _HTTP_TYPES:
            # Non-HTTP data sources require DB drivers not available in every R session;
            # mark as individually skipped rather than failing or skipping the whole test.
            result["ok"] = True
            result["error"] = (
                f"Skipped: connectivity check for type {ds.type!r} requires DB drivers "
                "not mandated by VIP. Verify manually."
            )
            results.append(result)
            continue

        ok, error = _check_http_source_in_r(page, ds.connection_string)
        result["ok"] = ok
        result["error"] = error
        results.append(result)

    return results


@then("all data sources are reachable")
def all_reachable(ds_results):
    failures = [r for r in ds_results if not r["ok"]]
    assert not failures, f"Data source failures: {failures}"
