"""Selftests for the Workbench Admin API client methods (#504).

Exercise the Bearer auth header, the launch/get/stop request shapes (including
the singular ``session_id`` vs plural ``session_ids`` gotcha), the
``wait_for_active`` poll helper, and the IDE-value map. No real network
connections are made: the client's internal httpx client is replaced with one
backed by ``httpx.MockTransport``.
"""

from __future__ import annotations

import json

import httpx
import pytest

from vip.clients.workbench import (
    SESSION_ACTIVE_STATE,
    SESSION_TERMINAL_FAILURE_STATES,
    WORKBENCH_IDE_VALUES,
    WorkbenchClient,
    WorkbenchSessionError,
)


def _mock_client(handler, *, api_key: str = "", auth_scheme: str = "Key") -> WorkbenchClient:
    """Build a WorkbenchClient whose httpx client uses a MockTransport.

    The Authorization header computed by the constructor is preserved so tests
    can assert on the auth scheme, unlike a bare replacement client.
    """
    wc = WorkbenchClient("https://wb.example.com", api_key=api_key, auth_scheme=auth_scheme)
    headers = dict(wc._client.headers)
    wc._client.close()
    wc._client = httpx.Client(
        base_url="https://wb.example.com",
        headers=headers,
        transport=httpx.MockTransport(handler),
    )
    return wc


# ---------------------------------------------------------------------------
# Auth scheme
# ---------------------------------------------------------------------------


def test_bearer_scheme_sets_authorization_header():
    captured: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"result": {"version": {"major": 2026}}})

    wc = _mock_client(handler, api_key="tok", auth_scheme="Bearer")
    wc.get_version()
    assert captured["auth"] == "Bearer tok"


def test_key_scheme_is_still_available_for_ui_cleanup_path():
    captured: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=[])

    wc = _mock_client(handler, api_key="tok", auth_scheme="Key")
    wc.list_sessions()
    assert captured["auth"] == "Key tok"


# ---------------------------------------------------------------------------
# launch_session
# ---------------------------------------------------------------------------


def test_launch_session_posts_method_and_kwparams_and_returns_result():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"result": {"id": "s-1", "url": "/s/abc", "project_id": "p-1"}},
        )

    wc = _mock_client(handler)
    result = wc.launch_session("RStudio", username="alice", name="VIP test_ide_launch_api.py - x")

    assert seen["path"] == "/api/launch_session"
    assert seen["body"]["method"] == "launch_session"
    assert seen["body"]["kwparams"] == {
        "workbench": "RStudio",
        "username": "alice",
        "name": "VIP test_ide_launch_api.py - x",
    }
    assert result == {"id": "s-1", "url": "/s/abc", "project_id": "p-1"}


def test_launch_session_omits_optional_kwparams_when_not_given():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"result": {"id": "s-2"}})

    wc = _mock_client(handler)
    wc.launch_session("VS Code")
    assert seen["body"]["kwparams"] == {"workbench": "VS Code"}


def test_launch_session_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "forbidden"})

    wc = _mock_client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        wc.launch_session("RStudio", username="alice")


# ---------------------------------------------------------------------------
# get_session / stop_session — singular vs plural key gotcha
# ---------------------------------------------------------------------------


def test_get_session_uses_singular_session_id_key():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"result": {"activity_state": "running"}})

    wc = _mock_client(handler)
    wc.get_session("s-1", username="alice", fields=["id", "activity_state"])

    assert seen["path"] == "/api/get_session"
    kwparams = seen["body"]["kwparams"]
    assert kwparams["session_id"] == "s-1"  # singular
    assert "session_ids" not in kwparams
    assert kwparams["user"] == "alice"  # from username
    assert kwparams["fields"] == ["id", "activity_state"]


def test_stop_session_uses_plural_session_ids_key():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"result": True})

    wc = _mock_client(handler)
    ok = wc.stop_session("s-1", force_quit=True)

    assert ok is True
    assert seen["path"] == "/api/stop_session"
    kwparams = seen["body"]["kwparams"]
    assert kwparams["session_ids"] == "s-1"  # plural
    assert "session_id" not in kwparams
    assert kwparams["force_quit"] is True


def test_stop_session_joins_multiple_ids():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200)

    wc = _mock_client(handler)
    wc.stop_session(["s-1", "s-2", "s-3"])
    assert seen["body"]["kwparams"]["session_ids"] == "s-1,s-2,s-3"


def test_stop_session_never_raises_returns_false_on_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    wc = _mock_client(handler)
    assert wc.stop_session("s-1") is False


def test_stop_session_returns_false_on_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    wc = _mock_client(handler)
    assert wc.stop_session("s-1") is False


# ---------------------------------------------------------------------------
# wait_for_active poll helper
# ---------------------------------------------------------------------------


def test_wait_for_active_returns_running_after_transition():
    states = iter(["starting", "starting", "running"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"activity_state": next(states)}})

    wc = _mock_client(handler)
    state = wc.wait_for_active("s-1", timeout=5, poll_interval=0)
    assert state == SESSION_ACTIVE_STATE


def test_wait_for_active_raises_on_terminal_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"activity_state": "failed"}})

    wc = _mock_client(handler)
    with pytest.raises(WorkbenchSessionError, match="terminal state"):
        wc.wait_for_active("s-1", timeout=5, poll_interval=0)


def test_wait_for_active_raises_on_timeout_when_stuck():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"activity_state": "starting"}})

    wc = _mock_client(handler)
    with pytest.raises(WorkbenchSessionError, match="did not reach"):
        # timeout=0 forces the deadline check to fire after the first poll.
        wc.wait_for_active("s-1", timeout=0, poll_interval=0)


def test_wait_for_active_reads_state_from_list_result():
    states = iter([[{"id": "s-1", "activity_state": "pending"}], [{"activity_state": "running"}]])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": next(states)})

    wc = _mock_client(handler)
    assert wc.wait_for_active("s-1", timeout=5, poll_interval=0) == "running"


# ---------------------------------------------------------------------------
# IDE value map — regression guard against a rename
# ---------------------------------------------------------------------------


def test_workbench_ide_values_are_exactly_the_five_docs_verified_values():
    assert WORKBENCH_IDE_VALUES == {
        "RStudio": "RStudio",
        "VS Code": "VS Code",
        "JupyterLab": "JupyterLab",
        "Jupyter Notebook": "Jupyter Notebook",
        "Positron": "Positron",
    }


@pytest.mark.parametrize("ide", ["RStudio", "VS Code", "JupyterLab", "Positron"])
def test_launch_covered_ides_are_present(ide):
    assert ide in WORKBENCH_IDE_VALUES


def test_terminal_failure_states_are_stable():
    assert SESSION_TERMINAL_FAILURE_STATES == ("failed", "killed")
    assert SESSION_ACTIVE_STATE == "running"
