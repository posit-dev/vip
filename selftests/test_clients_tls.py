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

import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

# ---------------------------------------------------------------------------
# Cert generation (openssl subprocess, no extra deps)
# ---------------------------------------------------------------------------


def _make_self_signed(certdir: Path) -> tuple[Path, Path]:
    """Generate a self-signed RSA cert/key pair in *certdir* and return paths.

    Uses ``openssl req`` so the ``cryptography`` package is not required.
    """
    cert_path = certdir / "cert.pem"
    key_path = certdir / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    return cert_path, key_path


# ---------------------------------------------------------------------------
# Minimal HTTPS server
# ---------------------------------------------------------------------------


class _OkHandler(BaseHTTPRequestHandler):
    """Return 200 OK for every GET."""

    def log_message(self, *args, **kwargs):  # noqa: D102
        pass  # suppress output during tests

    def do_GET(self):  # noqa: N802
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_tls_server(cert_path: Path, key_path: Path) -> tuple[ThreadingHTTPServer, str]:
    """Start a self-signed HTTPS server on an ephemeral port.

    Returns ``(server, url)`` where *url* is ``https://127.0.0.1:<port>``.
    The caller is responsible for calling ``server.shutdown()`` when done.
    """
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _OkHandler)
    # ThreadingHTTPServer defaults to non-daemon handler threads, which can
    # keep the test process alive past `serve_forever()` if a connection is
    # left open.  Match the pattern in selftests/test_load_engine.py.
    httpd.daemon_threads = True
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, f"https://127.0.0.1:{port}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tls_server(tmp_path_factory):
    """Shared self-signed HTTPS server for the module."""
    certdir = tmp_path_factory.mktemp("certs")
    cert, key = _make_self_signed(certdir)
    server, url = _start_tls_server(cert, key)
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
