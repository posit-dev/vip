"""Selftests for the TLS-version classification helper.

Covers ``_attempt_tls`` in ``src/vip_tests/cross_product/test_ssl.py``.
No real sockets: the handshake is monkeypatched to raise each exception
type in turn so we can assert how the helper classifies the result.
"""

from __future__ import annotations

import socket
import ssl

import pytest

from vip_tests.cross_product.test_ssl import _attempt_tls


def _patch_handshake(monkeypatch, exc: BaseException | None):
    """Make ``SSLContext.wrap_socket`` raise ``exc`` (or return a stub)."""

    class _StubSSLSocket:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_wrap_socket(self, sock, server_hostname=None, **kwargs):
        if exc is not None:
            raise exc
        return _StubSSLSocket()

    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", fake_wrap_socket)


def _patch_connect(monkeypatch, exc: BaseException | None = None):
    """Make ``socket.create_connection`` succeed with a stub or raise."""

    class _StubSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def close(self):
            pass

    def fake_create_connection(address, timeout=None):
        if exc is not None:
            raise exc
        return _StubSock()

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)


def test_attempt_tls_returns_connected_on_success(monkeypatch):
    _patch_connect(monkeypatch)
    _patch_handshake(monkeypatch, None)

    result = _attempt_tls("example.com", 443, min_version=ssl.TLSVersion.TLSv1_2)

    assert result == {"status": "connected", "detail": ""}


def test_attempt_tls_classifies_cert_verify_failure(monkeypatch):
    _patch_connect(monkeypatch)
    exc = ssl.SSLCertVerificationError(
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
        "unable to get local issuer certificate (_ssl.c:1000)"
    )
    _patch_handshake(monkeypatch, exc)

    result = _attempt_tls("example.com", 443, min_version=ssl.TLSVersion.TLSv1_2)

    assert result["status"] == "cert_verify_failed"
    assert "CERTIFICATE_VERIFY_FAILED" in result["detail"]


def test_attempt_tls_classifies_plain_ssl_error_as_rejected(monkeypatch):
    _patch_connect(monkeypatch)
    _patch_handshake(monkeypatch, ssl.SSLError("unsupported protocol"))

    result = _attempt_tls("example.com", 443, max_version=ssl.TLSVersion.TLSv1)

    assert result["status"] == "rejected"
    assert "unsupported protocol" in result["detail"]


def test_attempt_tls_classifies_oserror_as_rejected(monkeypatch):
    _patch_connect(monkeypatch)
    _patch_handshake(monkeypatch, OSError("handshake aborted"))

    result = _attempt_tls("example.com", 443, max_version=ssl.TLSVersion.TLSv1_1)

    assert result["status"] == "rejected"
    assert "handshake aborted" in result["detail"]


def test_attempt_tls_raises_connect_error_when_host_unreachable(monkeypatch):
    from vip_tests.cross_product.test_ssl import _ConnectError

    _patch_connect(monkeypatch, OSError("connection refused"))
    _patch_handshake(monkeypatch, None)

    with pytest.raises(_ConnectError) as info:
        _attempt_tls("example.com", 443, min_version=ssl.TLSVersion.TLSv1_2)

    assert "connection refused" in str(info.value)


def test_attempt_tls_classifies_context_config_failure_as_client_unsupported(
    monkeypatch,
):
    """Context-config failure (e.g. OpenSSL without TLS 1.0) reports
    ``client_unsupported`` so the caller can skip honestly instead of
    falsely counting it as a server rejection."""
    _patch_connect(monkeypatch)

    class _FakeContext:
        check_hostname = False
        verify_mode = ssl.CERT_NONE
        minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
        _max = ssl.TLSVersion.MAXIMUM_SUPPORTED

        @property
        def maximum_version(self):
            return self._max

        @maximum_version.setter
        def maximum_version(self, value):
            raise ssl.SSLError("no protocols available")

    monkeypatch.setattr(ssl, "create_default_context", lambda: _FakeContext())
    # Handshake won't run, but stub it anyway in case the helper reaches it.
    _patch_handshake(monkeypatch, None)

    result = _attempt_tls("example.com", 443, max_version=ssl.TLSVersion.TLSv1)

    assert result["status"] == "client_unsupported"
    assert "no protocols available" in result["detail"]
