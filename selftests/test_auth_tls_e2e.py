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
