"""Selftests for the Playwright-free step helpers in test_ide_launch_api.py (#504).

Covers the pure skip/fail decision helpers that gate the Workbench API
IDE-launch scenarios under ``--api-auth``:

- ``_api_privilege_skip`` — the actionable 401/403 skip message
- ``_ide_unavailable`` — classifying a 400 body as "IDE not installed" (skip)
  vs an unclassifiable error (fail)

No live Workbench deployment or Playwright browser is required. The step
functions themselves need a running server, but these helpers are pure and
decide skip-vs-fail, so they are worth guarding directly.
"""

from __future__ import annotations

import httpx
import pytest

from vip_tests.workbench.test_ide_launch_api import _api_privilege_skip, _ide_unavailable


class TestApiPrivilegeSkip:
    @pytest.mark.parametrize("code", [401, 403])
    def test_names_the_code_and_the_actionable_causes(self, code):
        msg = _api_privilege_skip(code)
        assert f"HTTP {code}" in msg
        # The message must point at the three load-bearing requirements so the
        # reader knows exactly why the API rejected the launch.
        assert "super-admin" in msg
        assert "workbench-api-super-admin-enabled=1" in msg
        assert "VIP_WORKBENCH_API_KEY" in msg


def _status_error(status_code: int, body: str) -> httpx.HTTPStatusError:
    """Build an HTTPStatusError whose response carries *body* as text."""
    request = httpx.Request("POST", "https://wb.example.com/api/launch_session")
    response = httpx.Response(status_code, text=body, request=request)
    return httpx.HTTPStatusError(f"{status_code}", request=request, response=response)


class TestIdeUnavailable:
    @pytest.mark.parametrize(
        "body",
        [
            "Unsupported workbench: Foo",
            "unknown workbench value",
            "That editor is not available on this server",
            "no such workbench",
            # Case-insensitivity: the classifier lowercases the body first.
            "UNSUPPORTED WORKBENCH",
        ],
    )
    def test_true_for_ide_not_installed_signals(self, body):
        assert _ide_unavailable(_status_error(400, body)) is True

    @pytest.mark.parametrize(
        "body",
        [
            "Internal server error",
            "launcher timed out starting the session",
            "",  # empty body cannot be classified
        ],
    )
    def test_false_for_unclassifiable_bodies(self, body):
        # An unclassifiable 400 is a real bug and must fail, not skip.
        assert _ide_unavailable(_status_error(400, body)) is False

    def test_false_when_reading_the_body_raises(self):
        # Defensive: a response whose .text access raises must not propagate —
        # the helper degrades to "not classified" (fail), never crashes.
        class _BoomResponse:
            @property
            def text(self) -> str:
                raise RuntimeError("body unreadable")

        class _Exc:
            response = _BoomResponse()

        assert _ide_unavailable(_Exc()) is False  # type: ignore[arg-type]
