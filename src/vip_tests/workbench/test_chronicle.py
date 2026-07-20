"""Step definitions for Workbench Chronicle observability tests.

Chronicle stores telemetry on the Workbench server and exposes no query API, so
the only way to prove it is collecting is to read the data back. Chronicle writes
raw ``chronicle-data-*`` chunk files under its storage path as it scrapes, and
only later compacts them into the daily/curated Parquet datasets that the
chronicle.reports R package reads. That compaction is deferred (hourly at best,
and the daily rollup lags real time by well over a day), so a freshly configured
deployment has *no* readable chronicle.reports data within any practical test
window. We therefore assert on the raw chunk files directly — the same signal
Posit's own Chronicle e2e suite uses to prove collection is live.

This test launches an RStudio session and, inside it, reads Chronicle's raw
chunk files to confirm it has written queryable telemetry for each of its two
*deterministically* collected paths, identified by a representative metric:

- Runtime metrics (Prometheus scrape) -> ``pwb_active_user_sessions``.
  Collected as soon as Chronicle is enabled (chronicle-enabled=1 + metrics-enabled=1).
- User information (Workbench admin API) -> ``pwb_users``.
  Requires ``workbench-api-admin-enabled=1``.

Reading in-session (rather than over SSH) also proves the session user can read
Chronicle's data directory — a real concern, since Chronicle writes group-only
permissions by default. Set ``[LocalStorage] Access = all`` in
chronicle-local.gcfg, or add the session user to the owning group.

Session events collected over OpenTelemetry logs are intentionally *not*
asserted here. That path is nondeterministic within a single test run (a session
launched by this test has not ended, so its lifecycle events are not flushed at
probe time) and is gated on the Monitoring license; Chronicle's own e2e suite
does not assert OTLP data landing either. See vip.toml.example for the exact
rserver.conf settings needed to enable Chronicle.

The session-lifecycle steps (login, start, becomes-active, IDE-displayed,
cleanup) are reimplemented here rather than imported from test_ide_launch:
pytest-bdd registers step decorators against the defining module, so
cross-module imports of @given/@when/@then functions do not register them for
the importer. This matches the pattern in test_packages.py and test_jobs.py.
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
from vip_tests.workbench.chronicle_probe import TOKEN_NO_DATA, TOKEN_OK, raw_chunk_probe_expr
from vip_tests.workbench.conftest import (
    TIMEOUT_CLEANUP,
    TIMEOUT_DIALOG,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_QUICK,
    assert_homepage_loaded,
    unique_session_name,
    wait_for_session_active,
    workbench_login,
)
from vip_tests.workbench.exec import rstudio_eval
from vip_tests.workbench.pages import Homepage, NewSessionDialog, RStudioSession

pytestmark = pytest.mark.order(60)

_FILENAME = Path(__file__).name

# Max time to allow for the in-session Chronicle data read. Walking the storage
# tree and reading a chunk file on a freshly started session can be slow.
_TIMEOUT_CHRONICLE_READ = 60_000


def _safe_r_literal(value: str, label: str) -> str:
    """Return *value* if safe to embed in an R string literal, else skip.

    Rejects an empty value or one containing a double quote, which would break
    out of the R string literal in the probe expression.
    """
    if not value:
        pytest.skip(f"{label} is empty in vip.toml")
    if '"' in value:
        pytest.skip(f"{label} contains an unsupported character: {value!r}")
    return value


def _probe_metric(page: Page, base_path: str, metric: str) -> str:
    """Run the raw-chunk probe in the session and return its sentinel token."""
    base_path = _safe_r_literal(base_path, "chronicle_data_path")
    metric = _safe_r_literal(metric, "chronicle metric name")
    expr = raw_chunk_probe_expr(base_path, metric)
    return rstudio_eval(page, expr, timeout=_TIMEOUT_CHRONICLE_READ)


def _assert_collected(
    page: Page, base_path: str, metric: str, path_label: str, remedy: str
) -> None:
    """Fail unless a readable, non-empty chunk exists for *metric*."""
    result = _probe_metric(page, base_path, metric)
    if TOKEN_OK in result:
        return
    if TOKEN_NO_DATA in result:
        pytest.fail(
            f"Found no readable Chronicle data chunk for {metric!r} under {base_path!r}, "
            f"so the {path_label} path is not producing data. {remedy} "
            "If the path is configured, Chronicle may not have collected yet — re-run "
            "after it has been running for a minute. The session user must also be able "
            "to read the data ([LocalStorage] Access = all in chronicle-local.gcfg, or "
            "group membership)."
        )
    pytest.fail(f"Unexpected output from Chronicle probe for {metric!r}: {result!r}")


@scenario("test_chronicle.feature", "Chronicle has collected telemetry readable in-session")
def test_chronicle_collects_data():
    pass


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------


@pytest.fixture
def session_context(page: Page, workbench_url: str):
    """Holds session name across steps, with best-effort cleanup on skip/fail."""
    ctx: dict = {"name": None, "cleaned_up": False}
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


@given("Chronicle verification is enabled in vip.toml")
def chronicle_enabled_guard(chronicle_enabled: bool):
    if not chronicle_enabled:
        pytest.skip(
            "Chronicle verification is disabled — set enabled = true under "
            "[chronicle] in vip.toml to enable it"
        )


@when("the user starts a new RStudio session")
def start_rstudio_session(page: Page, session_context: dict):
    session_name = unique_session_name(_FILENAME)
    session_context["name"] = session_name
    _start_session(page, "RStudio", session_name)


def _start_session(page: Page, ide_type: str, session_name: str):
    """Start a new session, leaving auto-join unchecked to observe state."""
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
    """Best-effort cancel of the New Session dialog, then ``pytest.skip``."""
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


@when("the session transitions to Active state")
def session_becomes_active(page: Page, session_context: dict):
    """Wait for the session to reach Active, then navigate into it."""
    session_name = session_context["name"]
    session_row = wait_for_session_active(page, session_name)

    session_link = session_row.locator(f"a[title='join {session_name}']")
    expect(session_link).to_be_visible(timeout=TIMEOUT_DIALOG)
    session_link.click()


@when("the RStudio IDE is displayed and functional")
def rstudio_functional(page: Page):
    """Verify RStudio IDE core elements are visible."""
    expect(page.locator(RStudioSession.LOGO)).to_be_visible(timeout=TIMEOUT_CLEANUP)
    expect(page.locator(RStudioSession.CONTAINER)).to_be_visible(timeout=TIMEOUT_DIALOG)
    expect(page.locator(RStudioSession.PROJECT_MENU)).to_be_visible(timeout=TIMEOUT_DIALOG)


@then("Chronicle has collected runtime metrics via the Prometheus scrape")
def chronicle_runtime_metrics(page: Page, vip_config: VIPConfig):
    """Runtime metrics: pwb_active_user_sessions from the Workbench /metrics scrape."""
    _assert_collected(
        page,
        vip_config.workbench.chronicle_data_path,
        "pwb_active_user_sessions",
        "runtime-metrics (Prometheus scrape)",
        "This path works once chronicle-enabled=1 and metrics-enabled=1 are set in rserver.conf.",
    )


@then("Chronicle has collected user information via the Workbench admin API")
def chronicle_user_information(page: Page, vip_config: VIPConfig):
    """User information: pwb_users from the Workbench admin API receiver."""
    _assert_collected(
        page,
        vip_config.workbench.chronicle_data_path,
        "pwb_users",
        "user-information (Workbench admin API)",
        "Enable it with workbench-api-admin-enabled=1 in rserver.conf.",
    )


@then("the session is cleaned up")
def session_cleaned_up(page: Page, workbench_url: str, session_context: dict):
    """Navigate back to homepage and quit the session."""
    session_name = session_context["name"]

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

    # Only mark cleaned up once the quit actually completed, so a failure above
    # still leaves the fixture finalizer to attempt best-effort cleanup.
    session_context["cleaned_up"] = True
