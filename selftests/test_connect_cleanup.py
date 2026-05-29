"""Selftests for ConnectClient VIP-content cleanup helpers.

No real network connections are made: the ConnectClient's internal httpx
client is replaced with one backed by httpx.MockTransport.  The client's
base URL includes the ``/__api__`` prefix so request paths look like
``/__api__/v1/content/<guid>``.
"""

from __future__ import annotations

import httpx

from vip.clients.connect import ConnectClient


def _client_with_handler(handler) -> ConnectClient:
    """Build a ConnectClient whose httpx client uses a MockTransport."""
    cc = ConnectClient("https://connect.example.com", api_key="k")
    cc._client.close()
    cc._client = httpx.Client(
        base_url="https://connect.example.com/__api__",
        transport=httpx.MockTransport(handler),
    )
    return cc


def test_cleanup_content_deletes_and_verifies():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "DELETE":
            return httpx.Response(200)
        if request.method == "GET":
            return httpx.Response(404)  # verify: confirmed gone
        return httpx.Response(200)

    cc = _client_with_handler(handler)
    assert cc.cleanup_content(["a", "b"]) == 2
    assert ("DELETE", "/__api__/v1/content/a") in calls
    assert ("DELETE", "/__api__/v1/content/b") in calls


def test_cleanup_content_idempotent_on_404_delete():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)  # DELETE 404 = already gone

    cc = _client_with_handler(handler)
    assert cc.cleanup_content(["a"]) == 1


def test_cleanup_content_retries_until_gone():
    get_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200)
        if request.method == "GET":
            get_calls["n"] += 1
            # Still present on first verify, gone on the second.
            return httpx.Response(200) if get_calls["n"] == 1 else httpx.Response(404)
        return httpx.Response(200)

    cc = _client_with_handler(handler)
    assert cc.cleanup_content(["a"], settle_seconds=0) == 1
    assert get_calls["n"] == 2


def test_cleanup_content_skips_falsy_guids():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(404)

    cc = _client_with_handler(handler)
    assert cc.cleanup_content(["", None]) == 0
    assert calls == []  # no requests issued for falsy guids


def test_cleanup_content_returns_zero_and_does_not_raise_on_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    cc = _client_with_handler(handler)
    assert cc.cleanup_content(["a"], retries=2, settle_seconds=0) == 0
