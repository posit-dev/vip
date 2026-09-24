"""Plain-function helpers shared by more than one selftest module.

These are ordinary functions called with arguments, not fixtures, so they
live here rather than in ``conftest.py``. ``selftests/`` has no
``__init__.py``, so pytest's default rootdir import mode puts it on
``sys.path`` and any selftest module can ``from _helpers import ...``.
"""

from __future__ import annotations

import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from vip.clients.workbench import WorkbenchClient

# ---------------------------------------------------------------------------
# TLS test server (cert generation + startup)
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


def _start_tls_server(
    cert_path: Path, key_path: Path, handler: type[BaseHTTPRequestHandler]
) -> tuple[ThreadingHTTPServer, str]:
    """Start a self-signed HTTPS server on an ephemeral port using *handler*.

    Returns ``(server, url)`` where *url* is ``https://127.0.0.1:<port>``.
    The caller is responsible for calling ``server.shutdown()`` when done.
    """
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
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
# Workbench MockTransport client
# ---------------------------------------------------------------------------


def _client_with_handler(handler) -> WorkbenchClient:
    """Build a WorkbenchClient whose httpx client uses a MockTransport."""
    wc = WorkbenchClient("https://wb.example.com")
    wc._client.close()
    wc._client = httpx.Client(
        base_url="https://wb.example.com",
        transport=httpx.MockTransport(handler),
    )
    return wc


# ---------------------------------------------------------------------------
# Package Manager repo dict builder
# ---------------------------------------------------------------------------


def _repo(name, type_=""):
    return {"name": name, "type": type_}
