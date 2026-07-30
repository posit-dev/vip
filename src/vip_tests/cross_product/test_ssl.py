"""Step definitions for SSL / HTTPS checks.

These tests specifically target common misconfigurations:
- Expired certificates
- Incomplete certificate chains (missing intermediate CA)
- HTTP not redirecting to HTTPS
"""

from __future__ import annotations

import socket
import ssl
from datetime import datetime, timezone
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
    if vip_config.insecure:
        # The user explicitly disabled certificate verification
        # (tls.insecure=true) — asserting cert validity contradicts that. #268.
        pytest.skip("tls.insecure=true — certificate validity checks are disabled")

    hostname = parsed.hostname
    port = parsed.port or 443

    try:
        sock = socket.create_connection((hostname, port), timeout=10)
    except OSError as exc:
        # DNS failure, connection refused, or a timed-out connect -- the
        # host is unreachable, which is not a certificate finding. Same
        # connect-vs-handshake split as ``_attempt_tls``/``_ConnectError``
        # below: only the TCP connect stage is skip-worthy. #555.
        pytest.skip(f"Could not connect to {hostname}:{port}: {exc}")

    ctx = ssl.create_default_context()
    try:
        with sock:
            with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                return {"cert": cert, "error": None, "hostname": hostname}
    except ssl.SSLCertVerificationError as exc:
        return {"cert": None, "error": str(exc), "hostname": hostname}
    # Deliberately no broader ``except Exception`` here: a handshake failure
    # for any other reason (a non-cert ssl.SSLError, a mid-handshake drop)
    # must propagate and fail loudly, not get silently reported as "not
    # applicable" -- that would gate this file's main new value, the
    # expiry-margin assertion in ``cert_valid``, behind a broad catch-all.


_MONTH_ABBREVIATIONS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}


def _cert_expires_at(cert: dict) -> datetime:
    """Parse the ``notAfter`` field from ``ssl.SSLSocket.getpeercert()``.

    The format is fixed by OpenSSL (e.g. ``"Jun  1 12:00:00 2030 GMT"``,
    always UTC) but is parsed with an explicit month-abbreviation lookup
    rather than ``strptime``: ``%b`` reads from the process's ``LC_TIME``
    month table, so on a non-English runner (e.g. ``LC_TIME=de_DE``)
    ``strptime`` would raise on this exact, unchanging string. VIP is
    customer-run software and does not control the runner's locale. #560.
    """
    not_after = cert.get("notAfter")
    if not not_after:
        raise ValueError("Certificate has no notAfter field")

    # split() collapses the extra space OpenSSL uses to pad a single-digit
    # day instead of zero-padding it (e.g. "Jun  1 ..."), so this handles
    # both single- and double-digit days without special-casing either.
    month_abbr, day, time_str, year, _tz = not_after.split()
    month = _MONTH_ABBREVIATIONS[month_abbr]
    hour, minute, second = (int(part) for part in time_str.split(":"))
    return datetime(int(year), month, int(day), hour, minute, second, tzinfo=timezone.utc)


@then("the certificate is valid and not expired")
def cert_valid(cert_info, vip_config):
    assert cert_info["error"] is None, f"SSL certificate error: {cert_info['error']}"
    assert cert_info["cert"] is not None, "No certificate returned"

    # A handshake succeeding only proves the cert isn't expired *yet* -- an
    # already-expired cert would have failed verification above. The useful
    # check is the margin: warn early enough to renew before the cert lapses
    # and causes an outage. See #555.
    expires_at = _cert_expires_at(cert_info["cert"])
    days_remaining = (expires_at - datetime.now(timezone.utc)).total_seconds() / 86400
    threshold = vip_config.cert_expiry_warning_days
    assert days_remaining >= threshold, (
        f"Certificate for {cert_info['hostname']} expires in "
        f"{days_remaining:.1f} day(s) (on {cert_info['cert']['notAfter']}), "
        f"under the configured {threshold}-day warning threshold "
        f"([tls] cert_expiry_warning_days). Renew it before it expires."
    )


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
    if urlparse(product_url).scheme != "https":
        # No HTTPS endpoint to redirect to on an HTTP-only deployment. See #268.
        pytest.skip(f"URL is not HTTPS: {product_url}")
    http_url = product_url.replace("https://", "http://", 1)
    parsed = urlparse(http_url)
    if parsed.scheme != "http":
        http_url = f"http://{parsed.hostname}"
    try:
        resp_no_follow = httpx.get(http_url, follow_redirects=False, timeout=10)
    except (httpx.NetworkError, httpx.ProtocolError) as exc:
        # NetworkError (ConnectError/ReadError/WriteError/CloseError) is a
        # refused, reset, or closed TCP connection; ProtocolError (its
        # subclass RemoteProtocolError in particular) is what a plaintext
        # HTTP request gets back from a TLS-only port. Both mean "no usable
        # plain-HTTP endpoint" for the checks below. In practice, hitting a
        # TLS-only port with plaintext HTTP has been observed to raise
        # EITHER RemoteProtocolError (server replies with a garbled TLS
        # byte httpx tries to parse as HTTP) OR ReadError/"Connection reset
        # by peer" (server just resets on non-TLS bytes) depending on the
        # server and OS -- confirmed against a live self-signed server,
        # not assumed -- so NetworkError, not just ConnectError, is needed.
        #
        # Deliberately NOT ``httpx.HTTPError`` (too wide) or a bare
        # ``except Exception`` (wider still): a timeout means the host is
        # filtered or hung, which is a materially different, reportable
        # state -- not "closed" -- so it must fall through and fail loudly.
        # An unrelated bug (httpx.InvalidURL from a malformed configured
        # URL, or a future edit introducing a NameError/AttributeError
        # here) must propagate as a real failure too, not get reported as
        # "port closed, that's fine" -- that would silently recreate the
        # exact vacuous-check problem this file's steps were just fixed
        # for. See #457, #555.
        # src/vip_tests/security/test_https.py::make_http_request classifies
        # its sibling check the same narrow way -- keep the two in sync.
        return {
            "status": None,
            "location": "",
            "final_url_scheme": None,
            "error": "port_closed",
            "detail": str(exc),
        }

    # Also follow redirects to detect ALB / load-balancer patterns where the
    # HTTP→HTTPS upgrade happens transparently (no client-visible 3xx).  This is
    # best-effort: a failure here must not discard the successful non-follow
    # response above, so swallow exceptions and leave the scheme unknown.
    final_url_scheme: str | None = None
    try:
        resp_followed = httpx.get(
            http_url, follow_redirects=True, timeout=10, verify=vip_config.verify
        )
        final_url_scheme = resp_followed.url.scheme
    except Exception:
        final_url_scheme = None

    return {
        "status": resp_no_follow.status_code,
        "location": resp_no_follow.headers.get("location", ""),
        "final_url_scheme": final_url_scheme,
        "error": None,
    }


@then("the response redirects to HTTPS")
def redirects_to_https(http_response):
    if http_response["error"] == "port_closed":
        # HTTP port not open is acceptable (handled by the "Or" clause).
        return

    # Primary path: a standard 3xx redirect with an https:// Location header.
    direct_redirect = http_response["status"] in (301, 302, 307, 308) and http_response[
        "location"
    ].startswith("https://")

    # Fallback path: following the redirect chain (including ALB/LB transparent
    # upgrades) ends up at an HTTPS URL — this is what a browser would observe.
    followed_to_https = http_response.get("final_url_scheme") == "https"

    assert direct_redirect or followed_to_https, (
        f"HTTP did not redirect to HTTPS. "
        f"Initial response: HTTP {http_response['status']}, "
        f"Location: {http_response['location']!r}, "
        f"final URL scheme after following redirects: {http_response.get('final_url_scheme')!r}"
    )


@then("the HTTP port is closed or serves no content directly")
def http_port_no_content(http_response):
    # This step is the narrower companion to "the response redirects to
    # HTTPS": a closed port is fine, and so is a redirect (already verified
    # above), but a 2xx response means the server served real content over
    # plaintext HTTP, which is never acceptable. See #555.
    if http_response["error"] == "port_closed":
        return
    status = http_response["status"]
    # Nothing legitimate reaches here with status=None: the only producer of
    # None is the port_closed branch above, which already returned. Assert
    # that explicitly rather than writing `status is None or ...`, which
    # would silently treat a future None-producing bug as "fine, no content".
    assert status is not None, (
        f"Expected an HTTP status since the port answered, got None "
        f"(error={http_response['error']!r})."
    )
    assert not (200 <= status < 300), (
        f"Plain HTTP served content directly (status {status}) instead of "
        "redirecting to HTTPS or refusing the connection."
    )


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
    insecure: bool = False,
    min_version: ssl.TLSVersion | None = None,
    max_version: ssl.TLSVersion | None = None,
    timeout: float = 10.0,
) -> dict:
    """Attempt one TLS handshake and classify the result.

    Uses ``ssl.create_default_context()`` so the system CA bundle is
    loaded (and ``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` are honored) --
    unless *insecure* is set, in which case certificate verification is
    disabled entirely. This scenario is about which TLS *versions* a server
    accepts, not certificate trust, so a user running with
    ``tls.insecure=true`` (e.g. against a self-signed cert) should still get
    a meaningful version-enforcement result instead of a cert-trust failure
    they already opted out of. See #457.

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
            if insecure:
                # check_hostname must be cleared before verify_mode, or
                # ssl raises ValueError("Cannot set verify_mode to
                # CERT_NONE when check_hostname is enabled").
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            else:
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
            "tls1_0": _attempt_tls(
                hostname,
                port,
                insecure=vip_config.insecure,
                min_version=ssl.TLSVersion.TLSv1,
                max_version=ssl.TLSVersion.TLSv1,
            ),
            "tls1_1": _attempt_tls(
                hostname,
                port,
                insecure=vip_config.insecure,
                min_version=ssl.TLSVersion.TLSv1_1,
                max_version=ssl.TLSVersion.TLSv1_1,
            ),
            "tls1_2": _attempt_tls(
                hostname, port, insecure=vip_config.insecure, min_version=ssl.TLSVersion.TLSv1_2
            ),
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

    # Carried alongside the per-version results (not iterated by the "TLS
    # 1.0/1.1" loop below, which only looks up the tls1_* keys) so
    # ``modern_tls_succeeds`` can give insecure-mode-aware guidance. #457.
    results["insecure"] = vip_config.insecure
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
        if tls_results.get("insecure"):
            # With tls.insecure=true, _attempt_tls disables verification
            # entirely, so this branch should be unreachable in practice --
            # but if it ever fires, the SSL_CERT_FILE guidance below would be
            # actively wrong: the user didn't misconfigure trust, they opted
            # out of it. #457.
            raise AssertionError(
                "TLS 1.2 handshake reached the server, but certificate "
                "verification failed even though tls.insecure=true disables "
                "it. This points to a TLS-stack problem, not a "
                "certificate-trust gap to configure around. "
                f"Detail: {detail}"
            )
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
