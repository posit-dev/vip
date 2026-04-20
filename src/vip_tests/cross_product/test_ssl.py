"""Step definitions for SSL / HTTPS checks.

These tests specifically target common misconfigurations:
- Expired certificates
- Incomplete certificate chains (missing intermediate CA)
- HTTP not redirecting to HTTPS
"""

from __future__ import annotations

import socket
import ssl
from urllib.parse import urlparse

import httpx
import pytest
from pytest_bdd import parsers, scenarios, then, when

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

scenarios("test_ssl.feature")


# ---------------------------------------------------------------------------
# Steps - SSL certificate checks
# ---------------------------------------------------------------------------


@when(parsers.parse("I check the SSL certificate for {product}"), target_fixture="cert_info")
def check_ssl_cert(product, vip_config):
    product_key = product.lower().replace(" ", "_")
    pc = vip_config.product_config(product_key)
    if not pc.is_configured:
        pytest.skip(f"{product} is not configured")

    product_url = pc.url
    parsed = urlparse(product_url)
    if parsed.scheme != "https":
        pytest.skip(f"URL is not HTTPS: {product_url}")

    hostname = parsed.hostname
    port = parsed.port or 443

    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((hostname, port), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                return {"cert": cert, "error": None}
    except ssl.SSLCertVerificationError as exc:
        return {"cert": None, "error": str(exc)}
    except Exception as exc:
        pytest.skip(f"Could not connect to {hostname}:{port}: {exc}")


@then("the certificate is valid and not expired")
def cert_valid(cert_info):
    assert cert_info["error"] is None, f"SSL certificate error: {cert_info['error']}"
    assert cert_info["cert"] is not None, "No certificate returned"


@then("the certificate chain is complete")
def cert_chain_complete(cert_info):
    # If we got here with create_default_context(), the chain was verified
    # by the system trust store.  An incomplete chain would have caused
    # SSLCertVerificationError above.
    assert cert_info["error"] is None, f"Certificate chain issue: {cert_info['error']}"


# ---------------------------------------------------------------------------
# Steps - HTTPS redirect
# ---------------------------------------------------------------------------


@when(parsers.parse("I request the HTTP URL for {product}"), target_fixture="http_response")
def request_http(product, vip_config):
    product_key = product.lower().replace(" ", "_")
    pc = vip_config.product_config(product_key)
    if not pc.is_configured:
        pytest.skip(f"{product} is not configured")

    product_url = pc.url
    http_url = product_url.replace("https://", "http://")
    parsed = urlparse(http_url)
    if parsed.scheme != "http":
        http_url = f"http://{parsed.hostname}"
    try:
        resp = httpx.get(http_url, follow_redirects=False, timeout=10)
        return {
            "status": resp.status_code,
            "location": resp.headers.get("location", ""),
            "error": None,
        }
    except httpx.ConnectError:
        return {"status": None, "location": "", "error": "port_closed"}
    except Exception as exc:
        return {"status": None, "location": "", "error": str(exc)}


@then("the response redirects to HTTPS")
def redirects_to_https(http_response):
    if http_response["error"] == "port_closed":
        # HTTP port not open is acceptable (handled by the "Or" clause).
        return
    assert http_response["status"] in (301, 302, 307, 308), (
        f"Expected redirect, got HTTP {http_response['status']}"
    )
    assert http_response["location"].startswith("https://"), (
        f"Redirect target is not HTTPS: {http_response['location']}"
    )


@then("the HTTP port is not open")
def http_port_closed(http_response):
    # This step is an alternative - if HTTP redirected, that's fine too.
    pass


# ---------------------------------------------------------------------------
# TLS attempt helper
# ---------------------------------------------------------------------------


class _ConnectError(Exception):
    """Raised by ``_attempt_tls`` when the TCP connect itself fails.

    Callers convert this into ``pytest.skip`` — an unreachable host is
    not a security finding.
    """


def _attempt_tls(
    hostname: str,
    port: int,
    *,
    min_version: ssl.TLSVersion | None = None,
    max_version: ssl.TLSVersion | None = None,
    timeout: float = 10.0,
) -> dict:
    """Attempt one TLS handshake and classify the result.

    Uses ``ssl.create_default_context()`` so the system CA bundle is
    loaded (and ``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` are honored).

    Returns a dict with:
      - ``status``: ``"connected"``, ``"rejected"``,
        ``"cert_verify_failed"``, or ``"client_unsupported"``
        (the last means the runner could not even configure the
        requested TLS version — the caller should skip rather than
        report this as a server rejection).
      - ``detail``: error string (empty when status is ``"connected"``).

    Raises ``_ConnectError`` when the TCP connect fails — the caller is
    expected to convert that into ``pytest.skip``.
    """
    try:
        sock = socket.create_connection((hostname, port), timeout=timeout)
    except OSError as exc:
        raise _ConnectError(str(exc)) from exc

    try:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED
            # ``create_default_context`` sets minimum_version = TLS 1.2 on
            # Python 3.10+.  Reset to the library minimum first so the
            # caller-specified window is applied cleanly — otherwise
            # ``max_version = TLSv1`` would violate the existing minimum.
            ctx.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
            if min_version is not None:
                ctx.minimum_version = min_version
            if max_version is not None:
                ctx.maximum_version = max_version
        except (ssl.SSLError, ValueError) as exc:
            # Some runtimes refuse to *configure* a given TLS version at all
            # (e.g. OpenSSL compiled without TLS 1.0/1.1 support).  Report
            # this honestly: the client cannot attempt that version, so we
            # have no data about the server's behavior.  The calling step
            # converts this into a skip for that scenario — silently
            # counting it as a server rejection would mask a client gap as
            # a server property.
            return {"status": "client_unsupported", "detail": str(exc)}

        try:
            with ctx.wrap_socket(sock, server_hostname=hostname):
                return {"status": "connected", "detail": ""}
        except ssl.SSLCertVerificationError as exc:
            return {"status": "cert_verify_failed", "detail": str(exc)}
        except (ssl.SSLError, OSError) as exc:
            return {"status": "rejected", "detail": str(exc)}
    finally:
        try:
            sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Steps - TLS version enforcement
# ---------------------------------------------------------------------------


@when(parsers.parse("I attempt a TLS connection to {product}"), target_fixture="tls_results")
def attempt_tls_connection(product, vip_config):
    product_key = product.lower().replace(" ", "_")
    pc = vip_config.product_config(product_key)
    if not pc.is_configured:
        pytest.skip(f"{product} is not configured")

    product_url = pc.url
    parsed = urlparse(product_url)
    if parsed.scheme != "https":
        pytest.skip(f"URL is not HTTPS: {product_url}")

    hostname = parsed.hostname
    port = parsed.port or 443

    try:
        results = {
            "tls1_0": _attempt_tls(hostname, port, max_version=ssl.TLSVersion.TLSv1),
            "tls1_1": _attempt_tls(hostname, port, max_version=ssl.TLSVersion.TLSv1_1),
            "tls1_2": _attempt_tls(hostname, port, min_version=ssl.TLSVersion.TLSv1_2),
        }
    except _ConnectError as exc:
        pytest.skip(f"Could not reach {hostname}:{port}: {exc}")

    unsupported = [
        label
        for label, key in (("TLS 1.0", "tls1_0"), ("TLS 1.1", "tls1_1"), ("TLS 1.2", "tls1_2"))
        if results[key]["status"] == "client_unsupported"
    ]
    if unsupported:
        pytest.skip(
            f"Runner cannot configure {', '.join(unsupported)} — cannot "
            f"assess server TLS enforcement on this client."
        )

    return results


@then("TLS 1.0 and TLS 1.1 connections are rejected")
def old_tls_rejected(tls_results):
    for label, key in (("TLS 1.0", "tls1_0"), ("TLS 1.1", "tls1_1")):
        result = tls_results.get(key, {})
        status = result.get("status")
        if status == "rejected":
            continue
        if status == "connected":
            raise AssertionError(
                f"Server accepted a {label} connection. Legacy TLS is not disabled."
            )
        if status == "cert_verify_failed":
            raise AssertionError(
                f"Server accepted a {label} handshake (the client then "
                f"failed cert verification, which happens after TLS version "
                f"negotiation). Legacy TLS is not disabled. "
                f"Detail: {result.get('detail', '')}"
            )
        raise AssertionError(f"Unexpected {label} result: {result!r}")


@then("TLS 1.2 or higher succeeds")
def modern_tls_succeeds(tls_results):
    result = tls_results.get("tls1_2", {})
    status = result.get("status")
    detail = result.get("detail", "")

    if status == "connected":
        return

    if status == "cert_verify_failed":
        raise AssertionError(
            "TLS 1.2 handshake reached the server, but the test runner "
            "could not verify the server's certificate. This is a "
            "certificate-trust issue on the runner, not a TLS-enforcement "
            "issue on the server. If the server uses a valid public "
            "certificate (e.g. behind an AWS ALB with an ACM cert), set "
            "SSL_CERT_FILE to a CA bundle that includes public roots: "
            "`/etc/ssl/certs/ca-certificates.crt` on Debian/Ubuntu, "
            "`/etc/pki/tls/certs/ca-bundle.crt` on RHEL, or the path "
            "produced by `python -m certifi`. "
            f"Detail: {detail}"
        )

    raise AssertionError(f"TLS 1.2 connection failed: {detail or status!r}")
