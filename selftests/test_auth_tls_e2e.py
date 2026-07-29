"""End-to-end TLS regression for _create_api_key_via_session.

Spins up a self-signed HTTPS server that mocks the three Connect endpoints
the mint flow touches (``/v1/user``, ``GET /v1/users/{guid}/keys``,
``POST /v1/users/{guid}/keys``), then calls ``_create_api_key_via_session``
with a stub ``Page`` and a real ``httpx.Client`` under the hood.

Before issue #239 was fixed, the mint path used Playwright's
``APIRequestContext`` and could not honor ``insecure=True`` against a
self-signed cert.  This test would have failed.

After the fix, ``insecure=True`` must produce a successful mint;
``insecure=False`` must return None gracefully (without raising) thanks
to the ``httpx.HTTPError`` catch added during code review.
"""

from __future__ import annotations

import json
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Self-signed cert + mock Connect server
# ---------------------------------------------------------------------------


def _make_self_signed(certdir: Path) -> tuple[Path, Path]:
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


_GUID = "user-guid-abc123"
_API_KEY = "vip-test-key-" + ("X" * 24)


class _ConnectMockHandler(BaseHTTPRequestHandler):
    """Minimal Connect API surface used by ``_create_api_key_via_session``."""

    def log_message(self, *args, **kwargs):  # noqa
        pass

    def _send_json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/__api__/v1/user":
            return self._send_json({"guid": _GUID})
        if self.path == f"/__api__/v1/users/{_GUID}/keys":
            return self._send_json([])  # no orphan keys
        return self._send_json({"error": f"unhandled GET {self.path}"}, status=404)

    def do_POST(self):  # noqa: N802
        if self.path == f"/__api__/v1/users/{_GUID}/keys":
            return self._send_json({"id": "1", "name": "x", "key": _API_KEY})
        return self._send_json({"error": f"unhandled POST {self.path}"}, status=404)


def _start_tls_server(cert: Path, key: Path) -> tuple[ThreadingHTTPServer, str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _ConnectMockHandler)
    # Avoid the test process hanging if a connection is still open at teardown.
    httpd.daemon_threads = True
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert), keyfile=str(key))
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"https://127.0.0.1:{port}"


@pytest.fixture(scope="module")
def connect_tls_server(tmp_path_factory):
    certdir = tmp_path_factory.mktemp("connect-tls")
    cert, key = _make_self_signed(certdir)
    server, url = _start_tls_server(cert, key)
    yield url
    server.shutdown()
    server.server_close()


def _start_http_redirect_server(https_base: str) -> tuple[ThreadingHTTPServer, str]:
    """Start a plaintext HTTP server that 307-redirects every request to
    the same path under *https_base*.

    Mirrors a deployment that terminates TLS at a reverse proxy and redirects
    plain HTTP to HTTPS -- the scenario from issue #537. Every request (GET
    and POST) is redirected, not just the first: ``httpx.Client.
    follow_redirects`` applies per request, and the mint flow issues three
    calls (GET /v1/user, GET .../keys, POST .../keys) against the same
    ``base_url``, each of which needs its own redirect to succeed.

    307 (not 301/302) is deliberate: it's the status code that preserves the
    method and body across the redirect, which is what a proxy has to use to
    avoid silently turning the mint flow's ``POST .../keys`` into a bodyless
    ``GET`` -- httpx (like every browser) downgrades POST to GET on 301/302
    for legacy compatibility. A proxy correctly configured for an API
    (as opposed to a browser-only redirect) uses 307/308 for exactly this
    reason.
    """

    class _RedirectHandler(BaseHTTPRequestHandler):
        def log_message(self, *args, **kwargs):  # noqa
            pass

        def _redirect(self) -> None:
            self.send_response(307)
            self.send_header("Location", f"{https_base}{self.path}")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            self._redirect()

        def do_POST(self) -> None:  # noqa: N802
            self._redirect()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _RedirectHandler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{port}"


@pytest.fixture(scope="module")
def connect_http_redirect_server(connect_tls_server: str):
    httpd, url = _start_http_redirect_server(connect_tls_server)
    yield url
    httpd.shutdown()
    httpd.server_close()


def _stub_page() -> MagicMock:
    """Return a Playwright Page stub with a usable session cookie jar."""
    page = MagicMock()
    page.context.cookies.return_value = [
        {"name": "RSC-XSRF", "value": "test-xsrf-token", "httpOnly": True},
        {"name": "connect-session", "value": "test-session", "httpOnly": True},
    ]
    return page


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_mint_succeeds_against_self_signed_when_insecure(connect_tls_server):
    """insecure=True must let the mint flow reach a self-signed Connect.

    Pre-fix (Playwright APIRequestContext), this would fail with
    CERTIFICATE_VERIFY_FAILED regardless of the insecure flag.
    """
    from vip.auth import _create_api_key_via_session

    page = _stub_page()
    api_key = _create_api_key_via_session(
        page,
        connect_tls_server,
        "test_vip_key",
        insecure=True,
    )
    assert api_key == _API_KEY


def test_mint_returns_none_against_self_signed_when_strict(connect_tls_server):
    """insecure=False against a self-signed cert returns None, not an exception.

    The httpx.HTTPError catch (added during code review) ensures vip verify
    surfaces a warning and continues instead of crashing during auth setup.
    """
    from vip.auth import _create_api_key_via_session

    page = _stub_page()
    api_key = _create_api_key_via_session(
        page,
        connect_tls_server,
        "test_vip_key",
        insecure=False,
    )
    assert api_key is None


def test_mint_follows_http_to_https_redirect(connect_http_redirect_server: str):
    """Reproduces issue #537 end-to-end: a Connect URL that resolves to a
    plaintext-HTTP endpoint which 307-redirects every request to HTTPS must
    still mint an API key.

    Before the fix, ``_create_api_key_via_session``'s ``httpx.Client`` left
    ``follow_redirects`` at its default (``False``), so the first
    ``GET /__api__/v1/user`` hit the redirect and was reported as a mint
    failure (returns ``None``) even though the server was healthy and
    reachable at the HTTPS location the redirect pointed to.
    """
    from vip.auth import _create_api_key_via_session

    page = _stub_page()
    api_key = _create_api_key_via_session(
        page,
        connect_http_redirect_server,
        "test_vip_key",
        insecure=True,  # the https side of the redirect uses a self-signed cert
    )
    assert api_key == _API_KEY
