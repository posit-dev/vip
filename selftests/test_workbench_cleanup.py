"""Selftests for WorkbenchClient VIP-session cleanup helpers.

No real network connections are made: the WorkbenchClient's internal
httpx client is replaced with one backed by httpx.MockTransport.
"""

from __future__ import annotations

import httpx
import pytest

from vip.clients.workbench import WorkbenchClient, is_vip_session


@pytest.mark.parametrize(
    "label, expected",
    [
        ("VIP test_ide_launch.py - gw0-123", True),
        ("VIP foo", True),
        ("_vip_cap_1700000000_default_0", True),
        ("My analysis", False),
        ("vip lowercase no space", False),
        ("", False),
    ],
)
def test_is_vip_session(label, expected):
    assert is_vip_session(label) is expected


def _client_with_handler(handler) -> WorkbenchClient:
    """Build a WorkbenchClient whose httpx client uses a MockTransport."""
    wc = WorkbenchClient("https://wb.example.com")
    wc._client.close()
    wc._client = httpx.Client(
        base_url="https://wb.example.com",
        transport=httpx.MockTransport(handler),
    )
    return wc


def test_quit_vip_sessions_targets_only_vip_and_skips_others():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/sessions":
            return httpx.Response(
                200,
                json=[
                    {"id": "a", "label": "VIP foo"},
                    {"id": "b", "label": "My real work"},
                    {"id": "c", "label": "_vip_cap_1_default_0"},
                ],
            )
        return httpx.Response(200)

    wc = _client_with_handler(handler)
    quit_count = wc.quit_vip_sessions(retries=1)

    assert quit_count == 2
    assert ("DELETE", "/api/sessions/a") in calls
    assert ("DELETE", "/api/sessions/c") in calls
    assert ("DELETE", "/api/sessions/b") not in calls


def test_quit_vip_sessions_retries_until_gone():
    list_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/sessions":
            list_calls["n"] += 1
            # First list shows the session; second list shows it gone.
            if list_calls["n"] == 1:
                return httpx.Response(200, json=[{"id": "a", "label": "VIP foo"}])
            return httpx.Response(200, json=[])
        return httpx.Response(200)

    wc = _client_with_handler(handler)
    quit_count = wc.quit_vip_sessions(retries=3, settle_seconds=0)

    assert quit_count == 1
    assert list_calls["n"] == 2  # stopped re-listing once the session was gone


def test_quit_vip_sessions_falls_back_to_suspend():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/sessions":
            return httpx.Response(200, json=[{"id": "a", "label": "VIP foo"}])
        if request.method == "DELETE":
            return httpx.Response(405)
        return httpx.Response(200)  # suspend succeeds

    wc = _client_with_handler(handler)
    quit_count = wc.quit_vip_sessions(retries=1)

    assert quit_count == 1
    assert ("DELETE", "/api/sessions/a") in calls
    assert ("POST", "/api/sessions/a/suspend") in calls


def test_quit_vip_sessions_returns_zero_on_non_200_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    wc = _client_with_handler(handler)
    assert wc.quit_vip_sessions(retries=2, settle_seconds=0) == 0


def test_quit_vip_sessions_does_not_raise_on_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    wc = _client_with_handler(handler)
    assert wc.quit_vip_sessions(retries=2, settle_seconds=0) == 0


def test_quit_vip_sessions_does_not_raise_on_invalid_json():
    """A 200 response whose body is not JSON must not raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    wc = _client_with_handler(handler)
    assert wc.quit_vip_sessions(retries=2, settle_seconds=0) == 0


def test_quit_vip_sessions_handles_non_list_body():
    """A 200 response whose JSON is not a list must not raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"oops": True})

    wc = _client_with_handler(handler)
    assert wc.quit_vip_sessions(retries=2, settle_seconds=0) == 0


def test_quit_vip_sessions_skips_null_label_and_non_dict_items():
    """Null labels and non-dict list items are skipped without raising."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/sessions":
            return httpx.Response(
                200,
                json=[
                    {"id": "a", "label": None},
                    "garbage",
                    42,
                    {"id": "b", "label": "VIP ok"},
                ],
            )
        return httpx.Response(200)

    wc = _client_with_handler(handler)
    # Only the valid VIP session is acted on; bad entries are ignored.
    assert wc.quit_vip_sessions(retries=1) == 1


def test_quit_vip_sessions_counts_unique_sessions_under_retry():
    """A session that persists across retries is counted once, not per attempt."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/sessions":
            # Always still listed → forces a fresh quit attempt each round.
            return httpx.Response(200, json=[{"id": "a", "label": "VIP stuck"}])
        return httpx.Response(200)  # DELETE "succeeds" but the session persists

    wc = _client_with_handler(handler)
    # 3 attempts each DELETE "a" successfully, but it is one unique session.
    assert wc.quit_vip_sessions(retries=3, settle_seconds=0) == 1


def test_sessions_api_reachable_true_on_200():
    wc = _client_with_handler(lambda r: httpx.Response(200, json=[]))
    assert wc.sessions_api_reachable() is True


def test_sessions_api_reachable_false_on_404():
    wc = _client_with_handler(lambda r: httpx.Response(404, text="<html>not found</html>"))
    assert wc.sessions_api_reachable() is False


def test_sessions_api_reachable_false_on_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    wc = _client_with_handler(handler)
    assert wc.sessions_api_reachable() is False


def test_vip_names_from_select_labels_keeps_only_vip():
    from vip_tests.workbench.conftest import _vip_names_from_select_labels

    labels = [
        "select VIP test_jobs.py - gw0-1",
        "select My real work",
        "select _vip_cap_1_default_0",
        "garbage without prefix",
        "VIP no select prefix",
    ]
    assert _vip_names_from_select_labels(labels) == [
        "VIP test_jobs.py - gw0-1",
        "_vip_cap_1_default_0",
    ]
