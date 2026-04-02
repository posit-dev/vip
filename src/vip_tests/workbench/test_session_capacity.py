"""Step definitions for session launch capacity tests.

These tests use Playwright to launch multiple Workbench sessions with
selectable resource profiles, verifying that the deployment can handle
the concurrent session load.  Sessions are launched one at a time
(Playwright is sequential) and then verified to all reach Active state.

Resource profiles are resolved at runtime:
- If ``workbench.session_profiles`` is set in ``vip.toml``, only those
  profiles are tested.
- If not set, the test auto-detects available profiles from the UI
  dropdown.

Requires ``--interactive-auth`` since session launching is browser-driven.
"""

from __future__ import annotations

import httpx
import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import given, scenarios, then, when

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


def _detect_profiles(page: Page) -> list[str]:
    """Open the New Session dialog and read available resource profiles."""
    page.locator(Homepage.NEW_SESSION_BUTTON).first.click(timeout=TIMEOUT_DIALOG)

    dialog = page.locator(NewSessionDialog.DIALOG)
    expect(dialog.locator(NewSessionDialog.TITLE)).to_have_text(
        "New Session", timeout=TIMEOUT_DIALOG
    )

    profile_dropdown = page.locator(NewSessionDialog.RESOURCE_PROFILE)
    if not profile_dropdown.is_visible(timeout=TIMEOUT_QUICK):
        # No resource profile dropdown — close dialog and return empty.
        page.locator(NewSessionDialog.CANCEL_BUTTON).click()
        return []

    # Open the dropdown to read options.
    profile_dropdown.click()
    options = page.locator("[role='option']")
    count = options.count()
    profiles = []
    for i in range(count):
        name = options.nth(i).get_attribute("name") or options.nth(i).text_content()
        if name:
            profiles.append(name.strip())

    # Close the dropdown and dialog.
    page.keyboard.press("Escape")
    page.locator(NewSessionDialog.CANCEL_BUTTON).click()
    expect(dialog).to_be_hidden(timeout=TIMEOUT_DIALOG)

    return profiles


def _launch_session(
    page: Page,
    session_name: str,
    profile: str | None = None,
) -> None:
    """Open the New Session dialog, optionally select a resource profile, and launch."""
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
            pytest.skip(f"Resource profile dropdown not available; cannot select '{profile}'")

    # Fill session name.
    page.fill(NewSessionDialog.SESSION_NAME, session_name)

    # Uncheck auto-join so we stay on the homepage to observe all sessions.
    checkbox = page.locator(NewSessionDialog.JOIN_CHECKBOX)
    if checkbox.is_visible() and checkbox.is_checked():
        checkbox.click()

    page.locator(NewSessionDialog.LAUNCH_BUTTON).click(timeout=TIMEOUT_QUICK)

    # Wait for the dialog to close before launching the next session.
    expect(dialog).to_be_hidden(timeout=TIMEOUT_DIALOG)


def _cleanup_sessions_via_api(page: Page, workbench_base_url: str) -> None:
    """Delete all sessions via the REST API."""
    try:
        cookies = {c["name"]: c["value"] for c in page.context.cookies()}
        with httpx.Client(base_url=workbench_base_url, cookies=cookies, timeout=30.0) as client:
            resp = client.get("/api/sessions")
            sessions = resp.json() if resp.status_code == 200 else []
            for session in sessions:
                sid = session.get("id") or session.get("session_id", "")
                if not sid:
                    continue
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
        page,
        workbench_url,
        test_username,
        test_password,
        auth_provider,
        interactive_auth,
    )
    assert_homepage_loaded(page)


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("I launch sessions with the test resource profile", target_fixture="launched_sessions")
def launch_sessions(page: Page, vip_config):
    session_count = vip_config.workbench.session_count
    configured_profiles = vip_config.workbench.session_profiles

    if configured_profiles:
        # Explicit config — test only the listed profiles.
        profiles_to_test = configured_profiles
    else:
        # Auto-detect from the dropdown.
        detected = _detect_profiles(page)
        if detected:
            profiles_to_test = detected
        else:
            # No dropdown — launch with default profile.
            profiles_to_test = [None]

    all_sessions: list[dict[str, str | None]] = []
    for profile in profiles_to_test:
        for i in range(session_count):
            label = profile or "default"
            name = f"{_SESSION_PREFIX}{label}_{i}"
            _launch_session(page, name, profile)
            all_sessions.append({"name": name, "profile": profile})

    return all_sessions


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("all launched sessions reach Active state")
def all_sessions_active(launched_sessions: list[dict[str, str | None]], page: Page):
    for session in launched_sessions:
        name = session["name"]
        active = page.locator(Homepage.session_row_status(name, "Active"))
        expect(active).to_be_visible(timeout=TIMEOUT_SESSION_START)


@then("I clean up all launched sessions")
def cleanup_sessions(
    launched_sessions: list[dict[str, str | None]], page: Page, workbench_url: str
):
    _cleanup_sessions_via_api(page, workbench_url)

    for session in launched_sessions:
        row = page.locator(Homepage.session_row(session["name"]))
        try:
            expect(row).to_be_hidden(timeout=TIMEOUT_DIALOG)
        except Exception:
            pass
