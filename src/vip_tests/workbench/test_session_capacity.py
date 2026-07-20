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

Requires ``--interactive-auth`` or ``--headless-auth`` since session launching is browser-driven.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import scenarios, then, when

from vip_tests.workbench.conftest import (
    TIMEOUT_DIALOG,
    TIMEOUT_QUICK,
    _quit_vip_sessions_via_cookies,
    format_capacity_failure,
    wait_for_session_active,
)
from vip_tests.workbench.pages import Homepage, NewSessionDialog

pytestmark = pytest.mark.order(40)

scenarios("test_session_capacity.feature")

# Unique prefix for session names. Timestamp ensures no collision with
# leftover sessions from previous runs.
_SESSION_PREFIX = f"_vip_cap_{int(__import__('time').time())}_"


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
        # No resource profile dropdown — close dialog via Escape.
        page.keyboard.press("Escape")
        expect(dialog).to_be_hidden(timeout=TIMEOUT_DIALOG)
        return []

    # Open the dropdown to read options.
    profile_dropdown.click()
    options = page.locator("[role='option']")
    options.first.wait_for(state="visible", timeout=TIMEOUT_QUICK)
    count = options.count()
    profiles = []
    for i in range(count):
        text = (options.nth(i).text_content() or "").strip()
        if text:
            profiles.append(text)

    # Close the dropdown, then close the dialog via Escape.
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
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

    # Explicitly select RStudio IDE tab to avoid relying on the default.
    rstudio_tab = dialog.get_by_role("tab", name="RStudio")
    if rstudio_tab.count() > 0:
        rstudio_tab.first.click(timeout=TIMEOUT_QUICK)

    # Select resource profile if specified and the dropdown exists.
    if profile is not None:
        profile_dropdown = page.locator(NewSessionDialog.RESOURCE_PROFILE)
        if profile_dropdown.is_visible(timeout=TIMEOUT_QUICK):
            # Use select_option for native <select> elements, or click
            # for custom dropdowns.
            tag = profile_dropdown.evaluate("el => el.tagName.toLowerCase()")
            if tag == "select":
                profile_dropdown.select_option(label=profile)
            else:
                profile_dropdown.click()
                page.wait_for_timeout(500)
                option = page.locator(f"[role='option']:has-text('{profile}')").first
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


def _cleanup_sessions_via_api(
    page: Page, workbench_base_url: str, *, insecure: bool, ca_bundle
) -> None:
    """Quit the VIP capacity sessions created by this test run.

    Delegates to the shared cookie-based cleanup helper, which targets all
    VIP-named sessions (``_vip_cap_`` prefix included).  TLS config is threaded
    through so cleanup works against self-signed / custom-CA deployments.
    """
    try:
        cookies = {c["name"]: c["value"] for c in page.context.cookies()}
    except Exception:
        return
    if not cookies:
        return
    _quit_vip_sessions_via_cookies(
        workbench_base_url, cookies, insecure=insecure, ca_bundle=ca_bundle
    )


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
            # No profiles dropdown — launch with default.
            profiles_to_test = [None]
        # When auto-detecting, launch 1 session per profile to avoid
        # overwhelming the cluster with many profiles × session_count.
        session_count = 1

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
    failures = []
    reasons = []
    for session in launched_sessions:
        name = session["name"]
        profile = session["profile"] or "default"
        # Fails fast when a session reaches a terminal state (e.g. Failed),
        # so a fully-broken launcher records all profiles quickly instead of
        # blocking the full session-start timeout per profile.  Keep the
        # diagnostic so the aggregated failure still names the terminal state
        # and its likely cause rather than only listing profiles.
        try:
            wait_for_session_active(page, name)
        except AssertionError as exc:
            failures.append(profile)
            reasons.append(str(exc))

    if failures:
        pytest.fail(format_capacity_failure(len(launched_sessions), failures, reasons))


@then("I clean up all launched sessions")
def cleanup_sessions(
    launched_sessions: list[dict[str, str | None]], page: Page, workbench_url: str, vip_config
):
    _cleanup_sessions_via_api(
        page, workbench_url, insecure=vip_config.insecure, ca_bundle=vip_config.ca_bundle
    )

    for session in launched_sessions:
        row = page.locator(Homepage.session_row(session["name"]))
        try:
            expect(row).to_be_hidden(timeout=TIMEOUT_DIALOG)
        except Exception:
            pass
