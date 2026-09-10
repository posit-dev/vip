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


def test_names_both_flags_when_mode_unknown():
    """When a caller forgets to thread the auth_mode fixture through,
    the message must not pick one flag arbitrarily — that would point
    users at the wrong flag.  Listing both is safe."""
    msg = _workbench_session_skip_message(
        auth_mode="none", workbench_auth_error=None, landed_url="https://wb/login"
    )
    assert "--interactive-auth" in msg
    assert "--headless-auth" in msg


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


class TestWorkbenchSessionSkipIsUnproven:
    """A configured Workbench whose auth never completed is #596's case.

    The deployment was explicitly asked for and could not be checked. That is
    the definition of unproven, so these skips must not be reported as the
    ordinary "nothing to do here" kind.
    """

    def test_raises_a_skip_flagged_unproven(self):
        import pytest

        from vip.attest import UNPROVEN_SENTINEL
        from vip_tests.workbench.conftest import _skip_workbench_session_unproven

        with pytest.raises(BaseException) as exc:
            _skip_workbench_session_unproven(
                auth_mode="headless",
                workbench_auth_error="timed out waiting for SSO redirect",
                landed_url="https://idp.example.com/login",
            )
        assert exc.typename == "Skipped"
        assert str(exc.value).startswith(UNPROVEN_SENTINEL)

    def test_message_still_carries_the_diagnostic_detail(self):
        import pytest

        from vip.plugin import _classify_skip_reason
        from vip_tests.workbench.conftest import _skip_workbench_session_unproven

        with pytest.raises(BaseException) as exc:
            _skip_workbench_session_unproven(
                auth_mode="headless",
                workbench_auth_error="timed out waiting for SSO redirect",
                landed_url="https://idp.example.com/login",
            )
        reason, unproven = _classify_skip_reason(str(exc.value))
        assert unproven is True
        # Classifying the skip must not cost the operator the actual cause.
        assert "--headless-auth" in reason
        assert "timed out waiting for SSO redirect" in reason
