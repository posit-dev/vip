"""Selftests for ConnectClient.fetch_content redirect handling.

These tests verify that relative Location headers are resolved against the
current response URL before the same-origin check and the follow-up GET,
preventing ``httpcore.UnsupportedProtocol`` when Connect returns paths like
``/content/{guid}/notebook.html``.

No real network connections are made: ``httpx.get`` is monkeypatched to
return pre-baked ``httpx.Response`` objects.
"""

from __future__ import annotations

import httpx

from vip.clients.connect import ConnectClient


def _make_response(
    status_code: int,
    *,
    url: str,
    location: str | None = None,
    body: bytes = b"",
) -> httpx.Response:
    """Build a minimal httpx.Response suitable for testing."""
    headers: dict[str, str] = {}
    if location is not None:
        headers["location"] = location
    return httpx.Response(
        status_code=status_code,
        headers=headers,
        content=body,
        request=httpx.Request("GET", url),
    )


def test_fetch_content_follows_relative_redirect(monkeypatch):
    """A relative Location like /content/abc/notebook.html is resolved and
    followed without raising UnsupportedProtocol."""

    base_url = "https://connect.example.com"
    initial_url = f"{base_url}/content/abc/"
    resolved_url = f"{base_url}/content/abc/notebook.html"
    expected_body = b"<html>notebook</html>"

    responses = {
        initial_url: _make_response(
            302,
            url=initial_url,
            location="/content/abc/notebook.html",
        ),
        resolved_url: _make_response(
            200,
            url=resolved_url,
            body=expected_body,
        ),
    }

    def fake_get(url, **kwargs):
        return responses[url]

    monkeypatch.setattr(httpx, "get", fake_get)

    client = ConnectClient(base_url=base_url, api_key="dummy-key")
    resp = client.fetch_content(initial_url)

    assert resp.status_code == 200
    assert resp.content == expected_body


def test_fetch_content_blocks_cross_origin_redirect(monkeypatch):
    """A redirect to a different hostname must not be followed (API key leak
    prevention).  The function should return the redirect response itself."""

    base_url = "https://connect.example.com"
    initial_url = f"{base_url}/content/abc/"

    redirect_resp = _make_response(
        302,
        url=initial_url,
        location="https://cdn.external.com/content/abc/notebook.html",
    )

    call_count = {"n": 0}

    def fake_get(url, **kwargs):
        call_count["n"] += 1
        # Only the first call (for initial_url) should ever happen.
        return redirect_resp

    monkeypatch.setattr(httpx, "get", fake_get)

    client = ConnectClient(base_url=base_url, api_key="dummy-key")
    resp = client.fetch_content(initial_url)

    # The redirect was not followed — the 302 is returned as-is.
    assert resp.status_code == 302
    # Only one GET was made (no follow-up to the external host).
    assert call_count["n"] == 1


def test_fetch_content_blocks_scheme_downgrade(monkeypatch):
    """A redirect from https to http on the same host must not be followed."""
    base_url = "https://connect.example.com"
    initial_url = f"{base_url}/content/abc/"

    redirect_resp = _make_response(
        302,
        url=initial_url,
        location="http://connect.example.com/content/abc/notebook.html",
    )

    call_count = {"n": 0}

    def fake_get(url, **kwargs):
        call_count["n"] += 1
        return redirect_resp

    monkeypatch.setattr(httpx, "get", fake_get)

    client = ConnectClient(base_url=base_url, api_key="dummy-key")
    resp = client.fetch_content(initial_url)

    assert resp.status_code == 302
    assert call_count["n"] == 1


def test_fetch_content_blocks_port_change(monkeypatch):
    """A redirect to a different port on the same host must not be followed."""
    base_url = "https://connect.example.com"
    initial_url = f"{base_url}/content/abc/"

    redirect_resp = _make_response(
        302,
        url=initial_url,
        location="https://connect.example.com:8443/content/abc/notebook.html",
    )

    call_count = {"n": 0}

    def fake_get(url, **kwargs):
        call_count["n"] += 1
        return redirect_resp

    monkeypatch.setattr(httpx, "get", fake_get)

    client = ConnectClient(base_url=base_url, api_key="dummy-key")
    resp = client.fetch_content(initial_url)

    assert resp.status_code == 302
    assert call_count["n"] == 1


def test_fetch_content_blocks_non_http_scheme(monkeypatch):
    """A redirect to a non-http(s) scheme must not be followed and must not raise."""
    base_url = "https://connect.example.com"
    initial_url = f"{base_url}/content/abc/"

    redirect_resp = _make_response(
        302,
        url=initial_url,
        location="file:///etc/passwd",
    )

    call_count = {"n": 0}

    def fake_get(url, **kwargs):
        call_count["n"] += 1
        return redirect_resp

    monkeypatch.setattr(httpx, "get", fake_get)

    client = ConnectClient(base_url=base_url, api_key="dummy-key")
    resp = client.fetch_content(initial_url)

    assert resp.status_code == 302
    assert call_count["n"] == 1


def test_fetch_content_allows_explicit_default_port(monkeypatch):
    """A redirect to the same origin with an explicit default port (443) is followed."""
    base_url = "https://connect.example.com"
    initial_url = f"{base_url}/content/abc/"
    resolved_url = "https://connect.example.com:443/content/abc/notebook.html"
    expected_body = b"<html>notebook</html>"

    responses = {
        initial_url: _make_response(
            302,
            url=initial_url,
            location="https://connect.example.com:443/content/abc/notebook.html",
        ),
        resolved_url: _make_response(
            200,
            url=resolved_url,
            body=expected_body,
        ),
    }

    def fake_get(url, **kwargs):
        return responses[url]

    monkeypatch.setattr(httpx, "get", fake_get)

    client = ConnectClient(base_url=base_url, api_key="dummy-key")
    resp = client.fetch_content(initial_url)

    assert resp.status_code == 200
    assert resp.content == expected_body


# ---------------------------------------------------------------------------
# TLS configuration round-trip tests
# ---------------------------------------------------------------------------


def test_connect_client_verify_false_when_insecure(monkeypatch):
    """ConnectClient with insecure=True passes verify=False to httpx.get."""
    base_url = "https://connect.example.com"
    initial_url = f"{base_url}/content/abc/"
    captured: list[dict] = []

    def fake_get(url, **kwargs):
        captured.append(kwargs)
        return _make_response(200, url=url, body=b"ok")

    monkeypatch.setattr(httpx, "get", fake_get)

    client = ConnectClient(base_url=base_url, api_key="key", insecure=True)
    client.fetch_content(initial_url)

    assert captured, "httpx.get was not called"
    assert captured[0].get("verify") is False


def test_connect_client_verify_ca_bundle(monkeypatch, tmp_path):
    """ConnectClient with ca_bundle set passes verify=<path> to httpx.get."""
    base_url = "https://connect.example.com"
    initial_url = f"{base_url}/content/abc/"
    bundle = tmp_path / "ca.pem"
    bundle.write_text("fake-pem")
    captured: list[dict] = []

    def fake_get(url, **kwargs):
        captured.append(kwargs)
        return _make_response(200, url=url, body=b"ok")

    monkeypatch.setattr(httpx, "get", fake_get)

    client = ConnectClient(base_url=base_url, api_key="key", ca_bundle=bundle)
    client.fetch_content(initial_url)

    assert captured, "httpx.get was not called"
    assert captured[0].get("verify") == str(bundle)


def test_connect_client_verify_true_by_default(monkeypatch):
    """ConnectClient without TLS flags passes verify=True to httpx.get."""
    base_url = "https://connect.example.com"
    initial_url = f"{base_url}/content/abc/"
    captured: list[dict] = []

    def fake_get(url, **kwargs):
        captured.append(kwargs)
        return _make_response(200, url=url, body=b"ok")

    monkeypatch.setattr(httpx, "get", fake_get)

    client = ConnectClient(base_url=base_url, api_key="key")
    client.fetch_content(initial_url)

    assert captured, "httpx.get was not called"
    assert captured[0].get("verify") is True
