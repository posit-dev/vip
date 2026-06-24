"""Tests for fail-fast detection when a Workbench session cannot launch.

A launched session that reaches a terminal "Failed" state will never become
Active.  Rather than waiting out the full session-start timeout and emitting
an opaque "Locator expected to be visible" error, the workbench helpers detect
the terminal state and fail fast with an actionable message.

These tests cover the pure pieces of that behavior: the session-status
selector (which must match both the legacy and the Workbench 2026.06 status
markup) and the failure-message builder.  The Playwright polling itself
requires a live Workbench and is exercised against a real deployment.
"""

from __future__ import annotations

from vip_tests.workbench.conftest import (
    TERMINAL_SESSION_FAILURE_STATES,
    _session_failure_message,
    format_capacity_failure,
)
from vip_tests.workbench.pages import Homepage


def test_failed_is_a_terminal_state():
    assert "Failed" in TERMINAL_SESSION_FAILURE_STATES


def test_failure_message_names_session_and_state():
    msg = _session_failure_message("VIP test - main-123", "Failed")
    assert "VIP test - main-123" in msg
    assert "Failed" in msg


def test_failure_message_explains_active_was_expected():
    msg = _session_failure_message("sess", "Failed")
    assert "Active" in msg


def test_failure_message_points_at_the_deployment_not_the_test():
    """The message must make clear the deployment could not launch the
    session, so the reader does not chase a phantom locator/test bug."""
    msg = _session_failure_message("sess", "Failed").lower()
    assert "workbench could not launch" in msg


def test_failure_message_supports_a_non_active_expected_state():
    """The suspend path expects 'Suspended', not 'Active'.  The message must
    name the expected state and must NOT misattribute the cause to a failed
    launch: the session did launch (it reached Active) and then abnormally
    exited during suspend."""
    msg = _session_failure_message("sess", "Failed", expected="Suspended")
    assert "Suspended" in msg
    assert "Failed" in msg
    assert "could not launch" not in msg.lower()


def test_wait_for_session_suspended_is_available():
    """The suspend step delegates to a fail-fast helper, mirroring
    wait_for_session_active, so a terminal 'Failed' is reported promptly
    instead of as an opaque timeout."""
    from vip_tests.workbench.conftest import wait_for_session_suspended

    assert callable(wait_for_session_suspended)


def test_status_selector_anchors_on_session_name():
    sel = Homepage.session_row_status("main-123", "Active")
    assert "tr[aria-label$='main-123']" in sel


def test_status_selector_matches_legacy_div_markup():
    """Workbench before 2026.06 rendered status as div[aria-label]."""
    sel = Homepage.session_row_status("s", "Active")
    assert "div[aria-label='Active']" in sel


def test_status_selector_matches_2026_06_button_markup():
    """Workbench 2026.06 renders status as a button whose accessible name is
    the status word (sourced from text or aria-label)."""
    sel = Homepage.session_row_status("s", "Failed")
    assert "button[aria-label='Failed']" in sel
    assert "button:text-is('Failed')" in sel


def test_capacity_failure_lists_counts_and_profiles():
    msg = format_capacity_failure(3, ["Small", "Large"], ["r1", "r2"])
    assert "1/3 sessions reached Active" in msg
    assert "Failed profiles: Small, Large" in msg


def test_capacity_failure_preserves_per_session_diagnostics():
    """The actionable per-session reason (terminal-state message) must survive
    aggregation, not be discarded in favor of a bare profile list."""
    reason = _session_failure_message("_vip_cap_Small_0", "Failed")
    msg = format_capacity_failure(1, ["Small"], [reason])
    assert reason in msg


def test_capacity_failure_without_reasons_still_lists_profiles():
    """A timeout path may record a profile without a captured reason; the
    profile list must still render."""
    msg = format_capacity_failure(2, ["Medium"], [])
    assert "1/2 sessions reached Active" in msg
    assert "Failed profiles: Medium" in msg
