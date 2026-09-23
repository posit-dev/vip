"""Regression tests: BaseClient and PackageManagerClient honor insecure=True.

Spins up a self-signed HTTPS server in a background thread (ephemeral port),
then verifies that:

- insecure=True  → request succeeds (200)
- insecure=False → request raises httpx.ConnectError (CERTIFICATE_VERIFY_FAILED)

This is the regression test that prevents the httpx transport+verify bug from
recurring.  When a custom ``transport=`` is passed to ``httpx.Client``, the
client-level ``verify`` argument is silently ignored; TLS config must be set on
the transport itself.  Without this test, a future refactor of
``BaseClient.__init__`` could re-introduce the same misconfig.

Cert generation uses subprocess + openssl so that no third-party packages beyond
the project's base requirements are needed.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler

import httpx
import pytest

from _helpers import _make_self_signed, _start_tls_server

# ---------------------------------------------------------------------------
# Minimal HTTPS server
# ---------------------------------------------------------------------------


class _OkHandler(BaseHTTPRequestHandler):
    """Return 200 OK for every GET."""

    def log_message(self, *args, **kwargs):
        pass  # suppress output during tests

    def do_GET(self):
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tls_server(tmp_path_factory):
    """Shared self-signed HTTPS server for the module."""
    certdir = tmp_path_factory.mktemp("certs")
    cert, key = _make_self_signed(certdir)
    server, url = _start_tls_server(cert, key, _OkHandler)
    yield url
    server.shutdown()
    server.server_close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_base_client_insecure_true_succeeds(tls_server):
    """BaseClient with insecure=True must reach a self-signed HTTPS server."""
    from vip.clients.base import BaseClient

    client = BaseClient(tls_server, insecure=True)
    try:
        resp = client._client.get("/")
        assert resp.status_code == 200
    finally:
        client.close()


def test_base_client_insecure_false_raises(tls_server):
    """BaseClient with insecure=False must fail against a self-signed cert."""
    from vip.clients.base import BaseClient

    client = BaseClient(tls_server, insecure=False)
    try:
        with pytest.raises(httpx.ConnectError):
            client._client.get("/")
    finally:
        client.close()


def test_package_manager_client_insecure_true_succeeds(tls_server):
    """PackageManagerClient with insecure=True must reach a self-signed server.

    _OkHandler returns 200 for every GET regardless of path, so reaching it
    at all proves TLS verification was disabled. We only care about the
    transport layer here, not the response shape.
    """
    from vip.clients.packagemanager import PackageManagerClient

    client = PackageManagerClient(tls_server, token="", insecure=True)
    try:
        # _client.get goes directly through the transport; bypass the typed
        # client methods to keep the test focused on TLS behavior.
        resp = client._client.get("/")
        assert resp.status_code == 200
    finally:
        client.close()


def test_package_manager_client_insecure_false_raises(tls_server):
    """PackageManagerClient with insecure=False must fail against self-signed cert."""
    from vip.clients.packagemanager import PackageManagerClient

    client = PackageManagerClient(tls_server, token="", insecure=False)
    try:
        with pytest.raises(httpx.ConnectError):
            client._client.get("/")
    finally:
        client.close()
