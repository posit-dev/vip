"""Tests for the workbench login skip-message helper.

When pre-test auth (--interactive-auth / --headless-auth) does not
establish a Workbench session, browser tests skip.  The helper named
here builds the user-facing skip text — naming the active mode's CLI
flag and quoting the underlying failure captured by
``_authenticate_workbench`` instead of guessing at the cause.
"""

from __future__ import annotations

from vip_tests.workbench.conftest import _workbench_session_skip_message


def test_names_headless_flag_when_active():
    msg = _workbench_session_skip_message(
        auth_mode="headless", workbench_auth_error=None, landed_url="https://wb/login"
    )
    assert "--headless-auth" in msg
    assert "--interactive-auth" not in msg
    assert "https://wb/login" in msg


def test_names_interactive_flag_when_active():
    msg = _workbench_session_skip_message(
        auth_mode="interactive", workbench_auth_error=None, landed_url="https://wb/login"
    )
    assert "--interactive-auth" in msg


def test_falls_back_to_interactive_flag_when_mode_unknown():
    msg = _workbench_session_skip_message(
        auth_mode="none", workbench_auth_error=None, landed_url="https://wb/login"
    )
    assert "--interactive-auth" in msg


def test_quotes_pre_test_auth_error_when_present():
    msg = _workbench_session_skip_message(
        auth_mode="headless",
        workbench_auth_error="Workbench authentication did not complete within 2 minutes",
        landed_url="https://wb/auth-sign-in",
    )
    assert "Pre-test auth reported:" in msg
    assert "Workbench authentication did not complete within 2 minutes" in msg


def test_omits_pre_test_error_section_when_none():
    msg = _workbench_session_skip_message(
        auth_mode="headless", workbench_auth_error=None, landed_url="https://wb/login"
    )
    assert "Pre-test auth reported:" not in msg
