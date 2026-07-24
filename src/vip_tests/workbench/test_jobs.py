"""Step definitions for Workbench job execution tests.

These tests verify that Background Jobs and Workbench Jobs (Launcher jobs)
can be submitted, executed, and produce expected output in an RStudio Pro session.

The job timeout is configurable via ``[workbench] job_timeout`` in vip.toml
(default: 120 seconds).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from pytest_bdd import given, scenario, then, when

from vip.config import VIPConfig
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
from vip_tests.workbench.pages import Homepage, NewSessionDialog, RStudioSession
from vip_tests.workbench.pages.console_pane import ConsolePaneSelectors

pytestmark = pytest.mark.order(60)

# R script that the job runs — output used for verification.
_JOB_SCRIPT_CONTENT = 'Sys.sleep(2)\ncat("hello from job\\n")'
_JOB_SCRIPT_FILENAME = "test_job_vip.R"
# Absolute, home-anchored path used for every file operation on the script.
# The R console writes and removes it, the Background Job dialog fills it, and
# the Workbench Job file chooser selects it. Anchoring to ~ (rather than a bare
# relative name resolved against the session's getwd()) guarantees the write
# step, the file chooser, and the cleanup step all reference the SAME file
# regardless of the working directory. R (writeLines/file.remove) and the
# RStudio file chooser both tilde-expand this path.
_JOB_SCRIPT_PATH = f"~/{_JOB_SCRIPT_FILENAME}"
_JOB_EXPECTED_OUTPUT = "hello from job"

_FILENAME = Path(__file__).name


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


@scenario("test_jobs.feature", "Background Job runs and completes")
def test_background_job():
    pass


@scenario("test_jobs.feature", "Workbench Job runs and completes")
def test_workbench_job():
    pass


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------


@pytest.fixture
def job_context(page: Page, workbench_url: str):
    """Holds session name and job type across steps, with best-effort cleanup."""
    ctx: dict = {"name": None, "cleaned_up": False, "job_type": None}
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


@when("the user starts a new RStudio Pro session for a job test")
def start_rstudio_session_for_job(page: Page, job_context: dict):
    """Open the new session dialog and launch an RStudio Pro session."""
    session_name = unique_session_name(_FILENAME)
    job_context["name"] = session_name

    page.locator(Homepage.NEW_SESSION_BUTTON).first.click(timeout=TIMEOUT_DIALOG)

    dialog = page.locator(NewSessionDialog.DIALOG)
    expect(dialog.locator(NewSessionDialog.TITLE)).to_have_text(
        "New Session", timeout=TIMEOUT_DIALOG
    )

    ide_display = NewSessionDialog.ide_display_name("RStudio")
    ide_tab = dialog.get_by_role("tab", name=ide_display)
    if ide_tab.count() == 0:
        cancel = page.locator(NewSessionDialog.CANCEL_BUTTON)
        if cancel.count() > 0:
            try:
                cancel.click(timeout=TIMEOUT_QUICK)
            except Exception:
                pass
        pytest.skip("RStudio Pro IDE not available in this Workbench deployment")

    ide_tab.click(timeout=TIMEOUT_QUICK)

    launch_btn = page.locator(NewSessionDialog.LAUNCH_BUTTON)
    try:
        launch_btn.wait_for(state="visible", timeout=TIMEOUT_QUICK)
    except PlaywrightTimeoutError:
        cancel = page.locator(NewSessionDialog.CANCEL_BUTTON)
        if cancel.count() > 0:
            try:
                cancel.click(timeout=TIMEOUT_QUICK)
            except Exception:
                pass
        pytest.skip(
            "RStudio Pro tab opened but Launch button did not appear — "
            "the IDE may not be installed or fully available on this Workbench instance"
        )

    page.fill(NewSessionDialog.SESSION_NAME, session_name)

    # Uncheck auto-join so we can observe state transitions on the homepage first.
    checkbox = page.locator(NewSessionDialog.JOIN_CHECKBOX)
    if checkbox.is_checked():
        checkbox.click()
    expect(checkbox).not_to_be_checked(timeout=TIMEOUT_QUICK)

    launch_btn.click(timeout=TIMEOUT_QUICK)


@when("the session reaches Active state")
def session_becomes_active(page: Page, job_context: dict):
    """Wait for the session to reach Active state."""
    wait_for_session_active(page, job_context["name"])


@when("the user joins the RStudio Pro session")
def join_rstudio_session(page: Page, job_context: dict):
    """Click the join link to navigate into the RStudio session."""
    session_name = job_context["name"]
    session_row = page.locator(Homepage.session_row(session_name))
    session_link = session_row.locator(f"a[title='join {session_name}']")
    expect(session_link).to_be_visible(timeout=TIMEOUT_DIALOG)
    session_link.click()


@when("the RStudio IDE loads successfully")
def rstudio_ide_loaded(page: Page):
    """Verify the RStudio IDE core elements are visible."""
    expect(page.locator(RStudioSession.LOGO)).to_be_visible(timeout=TIMEOUT_IDE_LOAD)
    expect(page.locator(RStudioSession.CONTAINER)).to_be_visible(timeout=TIMEOUT_DIALOG)
    # Wait for the console to become ready before interacting.
    expect(page.locator(ConsolePaneSelectors.INPUT)).to_be_visible(timeout=TIMEOUT_CODE_EXEC)


def _run_console_command(page: Page, r_cmd: str) -> None:
    """Type a single-line R expression into the console and submit it.

    The console input is an Ace editor <div>, not a real <input>/<textarea>,
    so Locator.fill() raises "Element is not an <input>...". Select-all +
    delete clears any leftover text, then real keystrokes are typed into the
    focused hidden Ace textarea (matches test_packages.py). ControlOrMeta maps
    select-all to Cmd+A on macOS, where Ctrl+A is "go to line start" and would
    not clear the input.
    """
    console_input = page.locator(ConsolePaneSelectors.INPUT)
    expect(console_input).to_be_visible(timeout=TIMEOUT_DIALOG)
    console_input.click()
    page.keyboard.press("ControlOrMeta+a")
    page.keyboard.press("Backspace")
    console_input.type(r_cmd)
    console_input.press("Enter")
    # Wait for the prompt to return (console is ready for next command).
    time.sleep(1)
    expect(console_input).to_be_visible(timeout=TIMEOUT_CODE_EXEC)


@when("the user writes a test R script file via the console")
def write_test_script(page: Page):
    """Write the test R script to a file using writeLines() and confirm it landed.

    The script is a two-line R program, but it must be typed as a single-line
    ``writeLines()`` call: the console is driven by Playwright .type(), which
    sends any real newline as an Enter keypress and would split the command in
    two. If the write is dropped or split, no file is created, the Workbench Job
    file chooser then silently rejects Open (the file must exist), and the
    readonly script field stays empty — surfacing later as an opaque empty-field
    error. Verify ``file.exists()`` right here so a bad write fails loudly at its
    source with the path, rather than masquerading as a chooser regression.
    """
    # _run_console_command types the command with Playwright .type(), which
    # sends a real newline (LF) as an Enter keypress. _JOB_SCRIPT_CONTENT holds a
    # two-line script separated by a literal LF, so the whole writeLines(...) call
    # must be escaped onto ONE physical line or Enter tears it in two — the first
    # fragment (writeLines("Sys.sleep(2)")) auto-closes and runs alone, the
    # remainder is a syntax error, and no file is written. Escape backslashes
    # first (so R sees single backslashes), then quotes, then the separator LF.
    escaped = _JOB_SCRIPT_CONTENT.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    # writeLines tilde-expands the path, so the file lands in the session home
    # directory — the same location the file chooser and cleanup step target.
    _run_console_command(page, f'writeLines("{escaped}", "{_JOB_SCRIPT_PATH}")')
    _assert_script_file_exists(page)


def _assert_script_file_exists(page: Page) -> None:
    """Fail loudly if the test script is not on disk after the write step.

    Emits a unique sentinel alongside ``file.exists()`` and reads it back from
    the console output, so a dropped ``writeLines()`` (or a write to an
    unexpected directory) is caught at the write step — before the file chooser
    turns it into an empty-script-field mystery.
    """
    marker = "VIP_JOB_SCRIPT_CHECK"
    _run_console_command(page, f'cat("{marker}:", file.exists("{_JOB_SCRIPT_PATH}"), "\\n")')
    output = page.locator(ConsolePaneSelectors.OUTPUT_ELEMENT)
    expect(
        output,
        (
            f"Test R script {_JOB_SCRIPT_PATH!r} was not created by the console write step — "
            f"the writeLines() keystrokes may have been dropped before the console settled, or "
            f"the file landed outside the session home directory"
        ),
    ).to_contain_text(f"{marker}: TRUE", timeout=TIMEOUT_CODE_EXEC)


@when("the user runs the script as a Background Job")
def run_as_background_job(page: Page, job_context: dict):
    """Open the Background Jobs pane and start the test script as a Background Job."""
    job_context["job_type"] = "background"

    # Click the Background Jobs tab in the console pane area.
    bg_tab = page.locator(RStudioSession.BACKGROUND_JOBS_TAB)
    try:
        bg_tab.wait_for(state="visible", timeout=TIMEOUT_DIALOG)
    except PlaywrightTimeoutError:
        pytest.skip(
            "Background Jobs tab not found — Background Jobs may not be available "
            "in this Workbench configuration"
        )
    bg_tab.click()

    # Click the Start Background Job button.
    start_btn = page.locator(RStudioSession.BACKGROUND_JOBS_START_BUTTON)
    try:
        start_btn.wait_for(state="visible", timeout=TIMEOUT_DIALOG)
    except PlaywrightTimeoutError:
        pytest.skip("Start Background Job button not found — cannot submit background job")
    start_btn.click()

    # Fill in the script path.
    script_input = page.locator(RStudioSession.BACKGROUND_JOB_SCRIPT_INPUT)
    try:
        script_input.wait_for(state="visible", timeout=TIMEOUT_DIALOG)
    except PlaywrightTimeoutError:
        pytest.skip("Background Job script input not found")
    script_input.fill(_JOB_SCRIPT_PATH)

    # Submit the job.
    run_btn = page.locator(RStudioSession.BACKGROUND_JOB_RUN_BUTTON)
    expect(run_btn).to_be_visible(timeout=TIMEOUT_QUICK)
    run_btn.click()


@when("the user runs the script as a Workbench Job")
def run_as_workbench_job(page: Page, job_context: dict):
    """Submit the test script as a Workbench Job (Launcher job) via the Jobs pane."""
    job_context["job_type"] = "workbench"

    # Click the Workbench Jobs pane tab.
    wb_tab = page.locator(RStudioSession.WORKBENCH_JOBS_TAB)
    try:
        wb_tab.wait_for(state="visible", timeout=TIMEOUT_DIALOG)
    except PlaywrightTimeoutError:
        pytest.skip(
            "Workbench Jobs tab not found — Workbench Jobs (Launcher) may not be available "
            "in this Workbench configuration"
        )
    wb_tab.first.click()

    # Click the Run Script as Workbench Job button.
    new_btn = page.locator(RStudioSession.WORKBENCH_JOB_NEW_BUTTON)
    try:
        new_btn.wait_for(state="visible", timeout=TIMEOUT_DIALOG)
    except PlaywrightTimeoutError:
        pytest.skip("Run Script as Workbench Job button not found")
    _open_workbench_job_dialog(page, new_btn)

    # Select the script via the file chooser. Unlike the Background Job dialog,
    # the Workbench Job dialog's script field (#rstudio_tbb_text_pro_job_script)
    # is a readonly FileChooserTextBox on Launcher deployments -- calling
    # fill() on it times out with "element is not editable". Instead click its
    # "Browse..." button, type the filename into the Choose File dialog, and
    # click Open, which populates the readonly field. (Verified live over CDP
    # against Workbench 2026.07.0.)
    _select_workbench_job_script(page, _JOB_SCRIPT_PATH)

    # Submit.
    submit_btn = page.locator(RStudioSession.WORKBENCH_JOB_SUBMIT_BUTTON)
    expect(submit_btn).to_be_visible(timeout=TIMEOUT_QUICK)
    submit_btn.click()


def _open_workbench_job_dialog(page: Page, new_btn) -> None:
    """Click the "Start Workbench Job" toolbar button until its dialog opens.

    The button is a GWT toolbar widget whose first click does not always open
    the "Run Script as Workbench Job" dialog — the click can land before the
    handler is armed, leaving the dialog closed and the later Browse-button
    wait to skip as if the feature were absent. Re-click a few times, checking
    for the Browse button (the dialog's first interactive control) between
    attempts, so a dropped first click self-heals instead of masquerading as a
    capability gap. Verified live over CDP against Workbench 2026.07.0.
    """
    browse_btn = page.locator(RStudioSession.WORKBENCH_JOB_SCRIPT_BROWSE_BUTTON).first
    for _ in range(3):
        new_btn.click()
        try:
            browse_btn.wait_for(state="visible", timeout=TIMEOUT_DIALOG)
            return
        except PlaywrightTimeoutError:
            continue
    # Final attempt surfaces the real state to _select_workbench_job_script,
    # which skips with a precise message if the Browse button never appears.
    new_btn.click()


def _fill_until_stable(locator, value: str, attempts: int = 5) -> None:
    """Fill *locator* with *value*, re-filling until the value stays put.

    The Workbench Job file chooser clears its name field ~1s after it first
    appears (GWT finishes initializing it), silently wiping an early fill(). Fill
    the field, wait past that reset window, and re-fill if it was cleared, so the
    value survives into the Open click regardless of when the reset lands.
    """
    for _ in range(attempts):
        locator.fill(value)
        # Wait out the chooser's post-init reset, then check the value held.
        locator.page.wait_for_timeout(TIMEOUT_QUICK // 4)
        if locator.input_value() == value:
            return
    # One last fill; the caller's downstream check reports an empty script field
    # with a precise message if the value still refuses to stick.
    locator.fill(value)


def _select_workbench_job_script(page: Page, script_filename: str) -> None:
    """Choose *script_filename* in the Workbench Job dialog via its file chooser.

    The script-path field is a readonly picker, so the path is set by driving
    the "Browse..." button → "Choose File" dialog → type name → Open, mirroring
    the RStudio Pro UI's only supported interaction. Skips gracefully if the
    dialog's controls are not present (an unexpected build variant) rather than
    hanging on an opaque timeout. Once the dialog IS open and Open is clicked,
    an empty script field is a real defect (not a capability gap), so it fails
    rather than skips.
    """
    browse_btn = page.locator(RStudioSession.WORKBENCH_JOB_SCRIPT_BROWSE_BUTTON).first
    try:
        browse_btn.wait_for(state="visible", timeout=TIMEOUT_DIALOG)
    except PlaywrightTimeoutError:
        pytest.skip("Workbench Job script Browse button not found in the submission dialog")
    browse_btn.click()

    # The Choose File dialog's name field IS editable -- type the filename there.
    name_input = page.locator(RStudioSession.FILE_CHOOSER_NAME_INPUT)
    try:
        name_input.wait_for(state="visible", timeout=TIMEOUT_DIALOG)
    except PlaywrightTimeoutError:
        pytest.skip("Workbench Job file chooser did not open")

    # The chooser clears the name field ~1s after it first appears, as GWT
    # finishes initializing it. A fill() that lands before that reset is wiped,
    # so Open then submits an empty name and the readonly script field stays
    # empty. Fill, then re-fill through the reset until the value sticks, before
    # clicking Open. Verified live over CDP against Workbench 2026.07.0.
    _fill_until_stable(name_input, script_filename)

    open_btn = page.locator(RStudioSession.FILE_CHOOSER_OPEN_BUTTON).first
    expect(open_btn).to_be_visible(timeout=TIMEOUT_QUICK)
    open_btn.click()

    # Confirm the readonly script field was populated before submitting. By this
    # point the dialog opened and Open was clicked, so Workbench Jobs IS
    # available on this deployment -- an empty field is a genuine regression
    # (rejected file, changed chooser contract), not a capability gap. Fail
    # loudly with the chosen path rather than skipping and masking the defect.
    script_field = page.locator(RStudioSession.WORKBENCH_JOB_SCRIPT_INPUT)
    expect(
        script_field,
        (
            f"Workbench Job script field stayed empty after choosing {script_filename!r} via "
            f"the file chooser — the file may not exist at that path, or the chooser contract "
            f"changed"
        ),
    ).not_to_have_value("", timeout=TIMEOUT_DIALOG)


def _wait_for_job_completion(page: Page, job_timeout_s: int) -> None:
    """Poll until the job shows a Succeeded/Completed status or the timeout expires."""
    status_locator = page.locator(RStudioSession.JOB_STATUS_SUCCEEDED)
    deadline = time.time() + job_timeout_s
    while time.time() < deadline:
        if status_locator.count() > 0 and status_locator.first.is_visible():
            return
        page.wait_for_timeout(1000)

    raise AssertionError(
        f"Job did not reach Succeeded/Completed status within {job_timeout_s}s — "
        "verify Launcher is operational and the Workbench deployment can execute jobs"
    )


@then("the Background Job completes with expected output")
def background_job_completed(page: Page, vip_config: VIPConfig):
    """Wait for the Background Job to complete and verify its output."""
    job_timeout_s = vip_config.workbench.job_timeout
    _wait_for_job_completion(page, job_timeout_s)

    output_area = page.locator(RStudioSession.JOB_OUTPUT_AREA)
    if output_area.count() > 0:
        output_text = output_area.first.text_content(timeout=TIMEOUT_QUICK) or ""
        assert _JOB_EXPECTED_OUTPUT in output_text, (
            f"Expected job output {_JOB_EXPECTED_OUTPUT!r} not found in job output: "
            f"{output_text[:200]!r}"
        )


@then("the Workbench Job completes with expected output")
def workbench_job_completed(page: Page, vip_config: VIPConfig):
    """Wait for the Workbench Job to complete and verify its output."""
    job_timeout_s = vip_config.workbench.job_timeout
    _wait_for_job_completion(page, job_timeout_s)

    output_area = page.locator(RStudioSession.JOB_OUTPUT_AREA)
    if output_area.count() > 0:
        output_text = output_area.first.text_content(timeout=TIMEOUT_QUICK) or ""
        assert _JOB_EXPECTED_OUTPUT in output_text, (
            f"Expected job output {_JOB_EXPECTED_OUTPUT!r} not found in job output: "
            f"{output_text[:200]!r}"
        )


@then("the test script file is removed")
def remove_test_script(page: Page):
    """Delete the test R script from the session home directory via the console.

    The job test writes ``test_job_vip.R`` into the session home directory
    (persistent shared storage on Workbench). Quitting the session does not
    remove it, so without this step the file accumulates across runs. Removes
    the same home-anchored path the write step created. Runs before the
    session-quit step while the console is still available. Best-effort: file
    cleanup must never fail the job result, so any error (console gone, command
    not accepted) is swallowed.
    """
    try:
        _run_console_command(page, f'suppressWarnings(file.remove("{_JOB_SCRIPT_PATH}"))')
    except Exception:
        pass


@then("the job test session is cleaned up")
def job_session_cleaned_up(page: Page, workbench_url: str, job_context: dict):
    """Navigate to the homepage and quit the test session."""
    session_name = job_context["name"]
    home_url = workbench_url.rstrip("/") + "/home"
    page.goto(home_url)
    expect(page.locator(Homepage.POSIT_LOGO)).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)

    checkbox = page.locator(Homepage.session_checkbox(session_name))
    try:
        expect(checkbox).to_be_visible(timeout=TIMEOUT_CLEANUP)
        checkbox.click()
        quit_btn = page.locator(Homepage.QUIT_BUTTON)
        expect(quit_btn).to_be_visible(timeout=TIMEOUT_QUICK)
        quit_btn.click()
        session_link = page.locator(Homepage.session_link(session_name))
        expect(session_link).not_to_be_visible(timeout=TIMEOUT_CLEANUP)
    except Exception:
        pass
    finally:
        job_context["cleaned_up"] = True
