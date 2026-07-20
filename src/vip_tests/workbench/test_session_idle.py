"""Step definitions for Workbench idle session auto-suspend behavior tests.

Two scenarios are covered:

1. An idle session auto-suspends after the deployment's configured timeout.
2. An active session driven by periodic console input is NOT suspended during
   the same window — verifying that activity correctly resets the idle clock.

Both scenarios skip when ``idle_timeout_minutes`` is not set in ``vip.toml``
or exceeds 15 minutes (the test ceiling for practical run times).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import given, scenario, then, when

from vip_tests.workbench.conftest import (
    TIMEOUT_CLEANUP,
    TIMEOUT_DIALOG,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_QUICK,
    TIMEOUT_SESSION_START,
    assert_homepage_loaded,
    raise_if_session_failed,
    unique_session_name,
    wait_for_session_active,
    workbench_login,
)
from vip_tests.workbench.exec import rstudio_eval
from vip_tests.workbench.pages import Homepage, NewSessionDialog

pytestmark = pytest.mark.order(45)

_FILENAME = Path(__file__).name

# Maximum idle_timeout_minutes that makes the test viable within CI/CD budgets.
MAX_VIABLE_IDLE_TIMEOUT_MINUTES = 15


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


@scenario("test_session_idle.feature", "Idle session auto-suspends after the configured timeout")
def test_idle_session_auto_suspends():
    pass


@scenario(
    "test_session_idle.feature",
    "Active session is not suspended while work is running",
)
def test_active_session_not_suspended():
    pass


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def idle_session_context():
    """Holds the session name across steps for idle tests."""
    return {"name": None}


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------


@given("the configured idle timeout is known", target_fixture="idle_timeout_minutes")
def configured_idle_timeout_known(vip_config):
    """Read idle_timeout_minutes from vip.toml and skip if absent or too large."""
    timeout = vip_config.workbench.idle_timeout_minutes
    if timeout is None:
        pytest.skip(
            "idle_timeout_minutes is not set in vip.toml — "
            "set [workbench] idle_timeout_minutes to the deployment's "
            "session-timeout-minutes value to enable this scenario"
        )
    if timeout > MAX_VIABLE_IDLE_TIMEOUT_MINUTES:
        pytest.skip(
            f"idle_timeout_minutes={timeout} exceeds the test ceiling of "
            f"{MAX_VIABLE_IDLE_TIMEOUT_MINUTES} min — configure the deployment "
            "with a shorter timeout to run these scenarios"
        )
    return timeout


@given("the configured idle grace window is known", target_fixture="idle_grace_seconds")
def configured_idle_grace_seconds(vip_config):
    """Read idle_grace_seconds from vip.toml (defaults to 60 s)."""
    return vip_config.workbench.idle_grace_seconds


@given("the user is logged in to Workbench for idle test")
def user_logged_in_for_idle(
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


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when("the user starts a new RStudio Pro session for idle testing")
def start_rstudio_session_for_idle(page: Page, idle_session_context: dict):
    """Launch a new RStudio Pro session without auto-joining."""
    session_name = unique_session_name(_FILENAME)
    idle_session_context["name"] = session_name

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


@when("the session reaches Active state for idle testing")
def session_becomes_active_for_idle(page: Page, idle_session_context: dict):
    """Wait for the session to reach Active state."""
    wait_for_session_active(page, idle_session_context["name"])


@when("the user leaves the session idle")
def leave_session_idle(page: Page):
    """Do nothing — the session is now idle on the homepage."""


@when("the user joins the session to perform work")
def join_session_for_work(page: Page, workbench_url: str, idle_session_context: dict):
    """Join the session so the RStudio console is available for eval."""
    session_name = idle_session_context["name"]
    session_row = page.locator(Homepage.session_row(session_name))
    expect(session_row).to_be_visible(timeout=TIMEOUT_DIALOG)
    join_link = page.locator(f"a[title='join {session_name}']")
    expect(join_link).to_be_visible(timeout=TIMEOUT_SESSION_START)
    join_link.click()
    page.wait_for_url("**/s/**", timeout=TIMEOUT_SESSION_START)
    page.wait_for_load_state("load", timeout=TIMEOUT_PAGE_LOAD)


@when("a long-running computation keeps the session active")
def keep_session_active_with_periodic_input(
    page: Page, idle_timeout_minutes: int, idle_grace_seconds: int
):
    """Drive the session with periodic console input events across the full idle window.

    Each ``rstudio_eval`` call types a trivial expression into the RStudio
    console, emitting an input event that resets Workbench's idle clock.
    The poll interval is derived from the idle timeout (at most half of it, and
    no more than 90 s) so the session is always nudged well before it would
    suspend — a hard-coded 90 s would let a short timeout (e.g. 1 min) suspend
    before the next nudge. Polling across
    ``idle_timeout_minutes * 60 + idle_grace_seconds`` seconds keeps the session
    alive for the entire window.
    """
    poll_interval_s = max(15, min(90, (idle_timeout_minutes * 60) // 2))
    end_time = time.monotonic() + (idle_timeout_minutes * 60) + idle_grace_seconds
    while time.monotonic() < end_time:
        rstudio_eval(page, "invisible(NULL)", timeout=15_000)
        remaining = end_time - time.monotonic()
        if remaining > 0:
            time.sleep(min(poll_interval_s, remaining))


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then("the session auto-suspends within the expected window")
def session_auto_suspends(
    page: Page,
    workbench_url: str,
    idle_session_context: dict,
    idle_timeout_minutes: int,
    idle_grace_seconds: int,
):
    """Assert the session reaches Suspended state within the expected window.

    The wait budget is ``idle_timeout_minutes * 60 + idle_grace_seconds`` seconds.
    The homepage does not auto-poll, so we reload periodically to observe the
    state transition.  If the session abnormally exits (terminal "Failed")
    instead of suspending, fail fast with an actionable message rather than
    reloading until the budget expires and emitting an opaque
    "Locator expected to be visible" error.
    """
    session_name = idle_session_context["name"]
    home_url = workbench_url.rstrip("/") + "/home"
    page.goto(home_url, timeout=TIMEOUT_PAGE_LOAD)
    assert_homepage_loaded(page)

    budget_s = (idle_timeout_minutes * 60) + idle_grace_seconds
    suspended = page.locator(Homepage.session_row_status(session_name, "Suspended"))
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        try:
            expect(suspended).to_be_visible(timeout=5_000)
            return
        except AssertionError:
            pass
        raise_if_session_failed(page, session_name, expected="Suspended")
        page.reload(timeout=TIMEOUT_PAGE_LOAD)
        assert_homepage_loaded(page)

    expect(suspended).to_be_visible(timeout=TIMEOUT_CLEANUP)


@then("the session remains Active at the end of the activity window")
def session_still_active(
    page: Page,
    workbench_url: str,
    idle_session_context: dict,
):
    """Navigate back to the homepage and assert the session is still Active."""
    session_name = idle_session_context["name"]
    home_url = workbench_url.rstrip("/") + "/home"
    page.goto(home_url, timeout=TIMEOUT_PAGE_LOAD)
    assert_homepage_loaded(page)

    active = page.locator(Homepage.session_row_status(session_name, "Active"))
    expect(active).to_be_visible(timeout=TIMEOUT_SESSION_START)


@then("the active idle session is cleaned up")
def cleanup_active_idle_session(page: Page, workbench_url: str, idle_session_context: dict):
    """Navigate to homepage and quit the test session."""
    session_name = idle_session_context["name"]
    home_url = workbench_url.rstrip("/") + "/home"
    page.goto(home_url)
    assert_homepage_loaded(page)

    checkbox = page.locator(Homepage.session_checkbox(session_name))
    expect(checkbox).to_be_visible(timeout=TIMEOUT_DIALOG)
    checkbox.click()

    quit_btn = page.locator(Homepage.QUIT_BUTTON)
    expect(quit_btn).to_be_visible(timeout=TIMEOUT_QUICK)
    quit_btn.click()

    session_link = page.locator(Homepage.session_link(session_name))
    expect(session_link).not_to_be_visible(timeout=TIMEOUT_CLEANUP)
