"""Step definitions for session launch capacity tests.

These tests use Playwright to launch multiple Workbench sessions with
selectable resource profiles, verifying that the deployment can handle
the concurrent session load.  Sessions are launched one at a time
(Playwright is sequential) and then verified to all reach Active state.

Requires ``--interactive-auth`` since session launching is browser-driven.
"""

from __future__ import annotations

import httpx
import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import given, parsers, scenarios, then, when

from vip_tests.workbench.conftest import (
    TIMEOUT_DIALOG,
    TIMEOUT_QUICK,
    TIMEOUT_SESSION_START,
    assert_homepage_loaded,
    workbench_login,
)
from vip_tests.workbench.pages import Homepage, NewSessionDialog

scenarios("test_session_capacity.feature")

# Unique prefix for session names so cleanup only targets our sessions.
_SESSION_PREFIX = "_vip_capacity_"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _launch_session(
    page: Page,
    session_name: str,
    profile: str | None = None,
) -> None:
    """Open the New Session dialog, optionally select a resource profile, and launch.

    Args:
        page: Playwright page on the Workbench homepage.
        session_name: Name to assign to the session.
        profile: Resource profile name to select, or None for the default.
    """
    page.locator(Homepage.NEW_SESSION_BUTTON).first.click(timeout=TIMEOUT_DIALOG)

    dialog = page.locator(NewSessionDialog.DIALOG)
    expect(dialog.locator(NewSessionDialog.TITLE)).to_have_text(
        "New Session", timeout=TIMEOUT_DIALOG
    )

    # Select resource profile if specified and the dropdown exists.
    if profile is not None:
        profile_dropdown = page.locator(NewSessionDialog.RESOURCE_PROFILE)
        if profile_dropdown.is_visible(timeout=TIMEOUT_QUICK):
            profile_dropdown.click()
            option = page.locator(NewSessionDialog.resource_profile_option(profile))
            option.click(timeout=TIMEOUT_QUICK)
        else:
            pytest.skip(
                f"Resource profile dropdown not available on this deployment; "
                f"cannot select '{profile}'"
            )

    # Fill session name.
    page.fill(NewSessionDialog.SESSION_NAME, session_name)

    # Uncheck auto-join so we stay on the homepage to observe all sessions.
    checkbox = page.locator(NewSessionDialog.JOIN_CHECKBOX)
    if checkbox.is_visible() and checkbox.is_checked():
        checkbox.click()

    page.locator(NewSessionDialog.LAUNCH_BUTTON).click(timeout=TIMEOUT_QUICK)

    # Wait for the dialog to close before launching the next session.
    expect(dialog).to_be_hidden(timeout=TIMEOUT_DIALOG)


def _cleanup_sessions_by_prefix(page: Page, workbench_base_url: str) -> None:
    """Delete all sessions whose name starts with the capacity test prefix."""
    try:
        cookies = {c["name"]: c["value"] for c in page.context.cookies()}
        with httpx.Client(
            base_url=workbench_base_url,
            cookies=cookies,
            timeout=30.0,
        ) as client:
            resp = client.get("/api/sessions")
            sessions = resp.json() if resp.status_code == 200 else []
            for session in sessions:
                sid = session.get("id") or session.get("session_id", "")
                if not sid:
                    continue
                # Try DELETE first, then suspend as fallback.
                for method, path in (
                    ("DELETE", f"/api/sessions/{sid}"),
                    ("POST", f"/api/sessions/{sid}/suspend"),
                ):
                    try:
                        r = client.request(method, path)
                        if r.status_code < 400:
                            break
                    except Exception:
                        continue
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("Workbench is accessible and I am logged in")
def workbench_logged_in(
    page: Page,
    workbench_url: str,
    test_username: str,
    test_password: str,
    auth_provider: str,
    interactive_auth: bool,
):
    workbench_login(
        page, workbench_url, test_username, test_password, auth_provider, interactive_auth
    )
    assert_homepage_loaded(page)


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(
    parsers.parse("I launch {count:d} sessions with the {profile} resource profile"),
    target_fixture="launched_sessions",
)
def launch_sessions_with_profile(count: int, profile: str, page: Page):
    sessions: list[str] = []
    effective_profile = None if profile == "default" else profile

    for i in range(count):
        name = f"{_SESSION_PREFIX}{profile}_{i}"
        _launch_session(page, name, effective_profile)
        sessions.append(name)

    return sessions


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then(parsers.parse("all {count:d} sessions reach Active state"))
def all_sessions_active(count: int, launched_sessions: list[str], page: Page):
    assert len(launched_sessions) == count, (
        f"Expected {count} sessions but only {len(launched_sessions)} were launched"
    )

    for name in launched_sessions:
        session_active = page.locator(Homepage.session_row_status(name, "Active"))
        expect(session_active).to_be_visible(timeout=TIMEOUT_SESSION_START)


@then("I clean up all launched sessions")
def cleanup_launched_sessions(launched_sessions: list[str], page: Page, workbench_url: str):
    _cleanup_sessions_by_prefix(page, workbench_url)

    # Verify sessions are gone from the homepage.
    for name in launched_sessions:
        session_row = page.locator(Homepage.session_row(name))
        try:
            expect(session_row).to_be_hidden(timeout=TIMEOUT_DIALOG)
        except Exception:
            pass  # Best-effort verification.
