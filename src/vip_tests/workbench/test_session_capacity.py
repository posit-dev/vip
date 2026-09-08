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

from dataclasses import dataclass

import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import scenarios, then, when

from vip import attest
from vip_tests.workbench.conftest import (
    TIMEOUT_DIALOG,
    TIMEOUT_QUICK,
    ResourceProfileDisabled,
    _option_is_disabled,
    capacity_session_prefix,
    format_capacity_failure,
    quit_owned_sessions_via_page,
    wait_for_session_active,
)
from vip_tests.workbench.pages import Homepage, NewSessionDialog

pytestmark = pytest.mark.order(40)

scenarios("test_session_capacity.feature")


@dataclass(frozen=True)
class DetectedProfile:
    """A resource profile discovered from the New Session dialog's dropdown.

    Disabled profiles are still reported so the caller can distinguish "no
    profiles at all" from "all profiles disabled for this user" and skip with
    an accurate reason.
    """

    name: str
    disabled: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_profiles(page: Page) -> list[DetectedProfile]:
    """Open the New Session dialog and read available resource profiles.

    Returns one :class:`DetectedProfile` per profile discovered, naming it and
    recording whether it is disabled for the authenticated user.
    """
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
    profiles: list[DetectedProfile] = []
    for i in range(count):
        option = options.nth(i)
        text = (option.text_content() or "").strip()
        if text:
            profiles.append(DetectedProfile(name=text, disabled=_option_is_disabled(option)))

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
    """Open the New Session dialog, optionally select a resource profile, and launch.

    Raises ``ResourceProfileDisabled`` if the selected profile is disabled for
    the authenticated user.
    """
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
                option.wait_for(state="visible", timeout=TIMEOUT_QUICK)
                if _option_is_disabled(option):
                    # Profile is offered but disabled for this user (e.g. a
                    # group-restricted profile). Clicking would just block
                    # until timeout, so close the dialog and signal the caller.
                    page.keyboard.press("Escape")
                    page.keyboard.press("Escape")
                    expect(dialog).to_be_hidden(timeout=TIMEOUT_DIALOG)
                    raise ResourceProfileDisabled(profile)
                option.click(timeout=TIMEOUT_QUICK)
        else:
            attest.unproven(f"Resource profile dropdown not available; cannot select '{profile}'")

    # Fill session name.
    page.fill(NewSessionDialog.SESSION_NAME, session_name)

    # Uncheck auto-join so we stay on the homepage to observe all sessions.
    checkbox = page.locator(NewSessionDialog.JOIN_CHECKBOX)
    if checkbox.is_visible() and checkbox.is_checked():
        checkbox.click()

    page.locator(NewSessionDialog.LAUNCH_BUTTON).click(timeout=TIMEOUT_QUICK)

    # Wait for the dialog to close before launching the next session.
    expect(dialog).to_be_hidden(timeout=TIMEOUT_DIALOG)


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
            enabled = [p.name for p in detected if not p.disabled]
            if not enabled:
                # Every profile is offered but disabled for this user — nothing
                # is launchable, so there is no capacity to exercise.
                names = ", ".join(p.name for p in detected)
                attest.not_applicable(
                    f"All resource profiles are disabled for the authenticated user: {names}"
                )
            profiles_to_test = enabled
        else:
            # No profiles dropdown — launch with default.
            profiles_to_test = [None]
        # When auto-detecting, launch 1 session per profile to avoid
        # overwhelming the cluster with many profiles × session_count.
        session_count = 1

    all_sessions: list[dict[str, str | None]] = []
    disabled_profiles: list[str] = []
    prefix = capacity_session_prefix()
    for profile in profiles_to_test:
        profile_disabled = False
        for i in range(session_count):
            label = profile or "default"
            name = f"{prefix}{label}_{i}"
            try:
                _launch_session(page, name, profile)
            except ResourceProfileDisabled as exc:
                # Configured profile the current user cannot launch. Treat as
                # an environment condition (entitlement/group restriction):
                # record it and move on to the remaining profiles rather than
                # aborting the whole scenario.
                disabled_profiles.append(exc.profile)
                profile_disabled = True
                break
            all_sessions.append({"name": name, "profile": profile})
        if profile_disabled:
            continue

    if not all_sessions and disabled_profiles:
        # No configured profile was launchable — there is no capacity to
        # exercise. Skip rather than fail so the scenario is reported as
        # skipped (not passed) on a correctly-restricted test account,
        # distinct from an actual capacity failure.
        names = ", ".join(disabled_profiles)
        attest.not_applicable(
            f"Resource profile(s) '{names}' are disabled for the authenticated "
            "user (likely a group/entitlement restriction)"
        )

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
    quit_owned_sessions_via_page(
        page, workbench_url, insecure=vip_config.insecure, ca_bundle=vip_config.ca_bundle
    )

    for session in launched_sessions:
        row = page.locator(Homepage.session_row(session["name"]))
        try:
            expect(row).to_be_hidden(timeout=TIMEOUT_DIALOG)
        except Exception:
            pass
