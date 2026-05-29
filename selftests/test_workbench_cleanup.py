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
