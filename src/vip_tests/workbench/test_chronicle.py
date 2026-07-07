"""Step definitions for Workbench Chronicle observability tests.

Chronicle stores telemetry as Parquet files on the Workbench server and exposes
no query API, so the only way to prove it is collecting is to read that data
back. This test launches an RStudio session and, inside it, uses the
chronicle.reports R package (https://github.com/posit-dev/chronicle-reports) to
confirm Chronicle has written queryable data for each of its three independent
collection paths, identified by the raw metric each path produces:

- Runtime metrics (Prometheus scrape) -> ``pwb_sessions_launched_total``.
  Collected as soon as Chronicle is enabled (chronicle-enabled=1 + metrics-enabled=1).
- User information (Workbench admin API) -> ``pwb_users``.
  Requires ``workbench-api-admin-enabled=1``.
- Session events (OpenTelemetry logs) -> ``pwb_sessions``.
  Requires the ``otel-*`` log-export settings plus a ``[Workbench] LogOTLPEndpoint``
  override and the Monitoring license feature.

Enabling ``chronicle_enabled`` asserts full Chronicle functionality: all three
paths must be configured and producing data. See vip.toml.example for the exact
rserver.conf / chronicle-local.gcfg settings.

The session-lifecycle steps (login, start, becomes-active, IDE-displayed,
cleanup) are reimplemented here rather than imported from test_ide_launch:
pytest-bdd registers step decorators against the defining module, so
cross-module imports of @given/@when/@then functions do not register them for
the importer. This matches the pattern in test_packages.py and test_jobs.py.

The session user must be able to read Chronicle's data directory (Chronicle
writes group-only permissions by default — set ``[LocalStorage] Access = all``
in chronicle-local.gcfg or add the session user to the owning group), and the
chronicle.reports package must be installed in the session's R library.
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
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_QUICK,
    assert_homepage_loaded,
    unique_session_name,
    wait_for_session_active,
    workbench_login,
)
from vip_tests.workbench.exec import rstudio_eval
from vip_tests.workbench.pages import Homepage, NewSessionDialog, RStudioSession

_FILENAME = Path(__file__).name

# Max time to allow for the in-session Chronicle data read. Opening and
# collecting a Parquet dataset on a freshly started session can be slow.
_TIMEOUT_CHRONICLE_READ = 90_000

# Tokens emitted by the in-session R probe (see _raw_metric_probe_expr).
_TOKEN_OK = "VIP_DATA_OK"
_TOKEN_NO_PKG = "VIP_NO_PKG"
_TOKEN_NO_DATA = "VIP_NO_DATA"


def _raw_metric_probe_expr(base_path: str, metric: str) -> str:
    """Build the single-line R expression that probes one raw Chronicle metric.

    Uses chronicle.reports to collect rows from *metric* at the configured base
    path, trying daily then hourly frequency. Prints exactly one sentinel token:

    - ``VIP_NO_PKG``   chronicle.reports is not installed in the session.
    - ``VIP_NO_DATA``  the metric directory is missing or yielded no rows
      (path not configured, nothing collected yet, or not readable).
    - ``VIP_DATA_OK``  the metric returned >= 1 row.

    ``base_path`` and ``metric`` are embedded as R string literals; callers must
    reject values containing a double quote (see ``_safe_r_literal``).
    """
    return (
        f'local({{ bp <- "{base_path}"; m <- "{metric}"; '
        'if (!requireNamespace("chronicle.reports", quietly = TRUE)) { '
        f'cat("{_TOKEN_NO_PKG}") }} else {{ '
        f'res <- "{_TOKEN_NO_DATA}"; '
        'for (f in c("daily", "hourly")) { '
        "n <- tryCatch(nrow(dplyr::collect(chronicle.reports::chronicle_raw_data(m, bp, f))), "
        "error = function(e) NA_integer_); "
        f'if (!is.na(n) && n > 0) {{ res <- "{_TOKEN_OK}"; break }} }}; '
        "cat(res) } })"
    )


def _safe_r_literal(value: str, label: str) -> str:
    """Return *value* if safe to embed in an R string literal, else skip.

    Rejects an empty value or one containing a double quote, which would break
    out of the R string literal in the probe expression.
    """
    if not value:
        pytest.skip(f"{label} is empty in vip.toml [workbench]")
    if '"' in value:
        pytest.skip(f"{label} contains an unsupported character: {value!r}")
    return value


def _probe_metric(page: Page, base_path: str, metric: str) -> str:
    """Run the raw-metric probe in the session and return its sentinel token.

    Skips the whole scenario when chronicle.reports is not installed, since the
    package is the verification mechanism, not the system under test.
    """
    base_path = _safe_r_literal(base_path, "chronicle_data_path")
    metric = _safe_r_literal(metric, "chronicle metric name")
    expr = _raw_metric_probe_expr(base_path, metric)
    result = rstudio_eval(page, expr, timeout=_TIMEOUT_CHRONICLE_READ)
    if _TOKEN_NO_PKG in result:
        pytest.skip(
            "chronicle.reports is not installed in the session's R library — "
            "install it (pak::pak('posit-dev/chronicle-reports')) to run this check"
        )
    return result


def _assert_collected(
    page: Page, base_path: str, metric: str, path_label: str, remedy: str
) -> None:
    """Fail unless the raw *metric* proving *path_label* has >= 1 collected row."""
    result = _probe_metric(page, base_path, metric)
    if _TOKEN_OK in result:
        return
    if _TOKEN_NO_DATA in result:
        pytest.fail(
            f"chronicle.reports found no rows for {metric!r} under {base_path!r}, "
            f"so the {path_label} path is not producing data. {remedy} "
            "If the path is configured, Chronicle may not have collected/flushed "
            "yet — re-run after it has been collecting for a while. The session "
            "user must also be able to read the data ([LocalStorage] Access = all "
            "in chronicle-local.gcfg, or group membership)."
        )
    pytest.fail(f"Unexpected output from Chronicle probe for {metric!r}: {result!r}")


@scenario("test_chronicle.feature", "Chronicle has collected telemetry across all three paths")
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
def chronicle_enabled_guard(vip_config: VIPConfig):
    if not vip_config.workbench.chronicle_enabled:
        pytest.skip(
            "Chronicle verification is disabled — set chronicle_enabled = true "
            "under [workbench] in vip.toml to enable it"
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
    """Path 1: pwb_sessions_launched_total from the Workbench /metrics scrape."""
    _assert_collected(
        page,
        vip_config.workbench.chronicle_data_path,
        "pwb_sessions_launched_total",
        "runtime-metrics (Prometheus scrape)",
        "This path works once chronicle-enabled=1 and metrics-enabled=1 are set in rserver.conf.",
    )


@then("Chronicle has collected user information via the Workbench admin API")
def chronicle_user_information(page: Page, vip_config: VIPConfig):
    """Path 3: pwb_users from the Workbench admin API receiver."""
    _assert_collected(
        page,
        vip_config.workbench.chronicle_data_path,
        "pwb_users",
        "user-information (Workbench admin API)",
        "Enable it with workbench-api-admin-enabled=1 in rserver.conf.",
    )


@then("Chronicle has collected session events via OTLP")
def chronicle_session_events(page: Page, vip_config: VIPConfig):
    """Path 2: pwb_sessions from OpenTelemetry log export."""
    _assert_collected(
        page,
        vip_config.workbench.chronicle_data_path,
        "pwb_sessions",
        "session-events (OpenTelemetry logs)",
        "Enable it with otel-enabled=1 / otel-logs-enabled=1 / otel-logs-endpoint "
        "in rserver.conf and [Workbench] LogOTLPEndpoint in chronicle-local.gcfg; "
        "OTLP export requires the Monitoring license feature.",
    )


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
