"""Selftests for ``make_http_request`` in
``src/vip_tests/security/test_https.py``.

Mirrors ``selftests/test_ssl_helper.py``'s coverage of the sibling
``request_http`` -- both classify "no usable plain-HTTP endpoint" the same
narrow way (``httpx.NetworkError``/``httpx.ProtocolError`` only, NOT the
wider ``httpx.HTTPError``), so a timeout or an unrelated exception (a
malformed URL, a code bug) still propagates instead of being reported as an
acceptable "port closed" outcome. See #457, #555.
"""

from __future__ import annotations

import httpx
import pytest

from vip.config import VIPConfig
from vip_tests.security.test_https import make_http_request


def test_make_http_request_classifies_connect_error_as_refused(monkeypatch):
    def fake_get(url, follow_redirects=False, timeout=10, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx, "get", fake_get)

    result = make_http_request("https://connect.example.com", VIPConfig())

    assert result["refused"] is True


def test_make_http_request_classifies_protocol_error_as_refused(monkeypatch):
    """A plaintext request landing on a TLS-only port raises a protocol
    error, not ``httpx.ConnectError`` -- it must still classify as
    "refused" so ``https_enforced`` treats a missing plain-HTTP listener as
    acceptable. #457."""

    def fake_get(url, follow_redirects=False, timeout=10, **kwargs):
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.")

    monkeypatch.setattr(httpx, "get", fake_get)

    result = make_http_request("https://connect.example.com", VIPConfig())

    assert result["refused"] is True


def test_make_http_request_classifies_read_error_as_refused(monkeypatch):
    """Confirmed against a live self-signed server (not assumed): hitting a
    TLS-only port with plaintext HTTP can also surface as
    ``httpx.ReadError``/"Connection reset by peer" rather than
    ``RemoteProtocolError``, depending on the server and OS. ``ReadError``
    is an ``httpx.NetworkError``, NOT an ``httpx.ConnectError`` or
    ``httpx.ProtocolError``, which is why the except clause must catch
    ``NetworkError`` rather than just ``ConnectError``. #457."""

    def fake_get(url, follow_redirects=False, timeout=10, **kwargs):
        raise httpx.ReadError("[Errno 54] Connection reset by peer")

    monkeypatch.setattr(httpx, "get", fake_get)

    result = make_http_request("https://connect.example.com", VIPConfig())

    assert result["refused"] is True


def test_make_http_request_does_not_swallow_unrelated_exceptions(monkeypatch):
    """Regression guard: classifying every exception as "refused" would let
    ``https_enforced`` pass silently on a malformed URL or a code bug, not
    just on a genuinely closed port. ``httpx.InvalidURL`` derives directly
    from ``Exception`` (not ``httpx.HTTPError``), so it must propagate. #457.
    """

    def fake_get(url, follow_redirects=False, timeout=10, **kwargs):
        raise httpx.InvalidURL("Invalid URL component 'host'")

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(httpx.InvalidURL):
        make_http_request("https://connect.example.com", VIPConfig())


def test_make_http_request_does_not_swallow_programming_errors(monkeypatch):
    def fake_get(url, follow_redirects=False, timeout=10, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(RuntimeError, match="boom"):
        make_http_request("https://connect.example.com", VIPConfig())


def test_make_http_request_does_not_classify_connect_timeout_as_refused(monkeypatch):
    """A timeout means the host is filtered or hung, not "no plain-HTTP
    listener" -- ``httpx.ConnectTimeout`` is a ``TimeoutException``, NOT an
    ``httpx.NetworkError``/``ProtocolError``, so it must propagate. #457.
    """

    def fake_get(url, follow_redirects=False, timeout=10, **kwargs):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(httpx.ConnectTimeout):
        make_http_request("https://connect.example.com", VIPConfig())


def test_make_http_request_does_not_classify_read_timeout_as_refused(monkeypatch):
    """A ``ReadTimeout`` means the port accepted the connection and never
    answered -- a hung listener, a real bug, not "port closed". #457."""

    def fake_get(url, follow_redirects=False, timeout=10, **kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(httpx.ReadTimeout):
        make_http_request("https://connect.example.com", VIPConfig())
