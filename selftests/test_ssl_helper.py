"""Selftests for the step definitions in
``src/vip_tests/cross_product/test_ssl.py``.

No real sockets: handshakes, connects, and HTTP requests are monkeypatched
so we can assert how each step classifies results and where its assertions
actually fail.
"""

from __future__ import annotations

import locale
import socket
import ssl
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from vip.config import ConnectConfig, VIPConfig
from vip_tests.cross_product.test_ssl import (
    _attempt_tls,
    _cert_expires_at,
    cert_valid,
    check_ssl_cert,
    http_port_no_content,
    request_http,
)


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


def _recording_context_factory(seen: dict):
    """Build a fake ``create_default_context()`` replacement that records
    every attribute assignment into *seen* and answers ``wrap_socket`` with
    a stub context manager (no real handshake)."""

    class _StubSSLSocket:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _RecordingContext:
        minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
        maximum_version = ssl.TLSVersion.MAXIMUM_SUPPORTED

        def __setattr__(self, name, value):
            seen[name] = value
            object.__setattr__(self, name, value)

        def wrap_socket(self, sock, server_hostname=None, **kwargs):
            return _StubSSLSocket()

    return _RecordingContext


def test_attempt_tls_defaults_to_full_verification(monkeypatch):
    """Without ``insecure``, the context must require and check certs."""
    _patch_connect(monkeypatch)

    seen: dict = {}
    monkeypatch.setattr(ssl, "create_default_context", lambda: _recording_context_factory(seen)())

    _attempt_tls("example.com", 443, min_version=ssl.TLSVersion.TLSv1_2)

    assert seen["check_hostname"] is True
    assert seen["verify_mode"] == ssl.CERT_REQUIRED


def test_attempt_tls_insecure_disables_verification(monkeypatch):
    """``insecure=True`` (mirrors ``tls.insecure``) must relax verification
    so a self-signed cert doesn't masquerade as a TLS-version failure. #457.
    """
    _patch_connect(monkeypatch)

    seen: dict = {}
    monkeypatch.setattr(ssl, "create_default_context", lambda: _recording_context_factory(seen)())

    result = _attempt_tls("example.com", 443, insecure=True, min_version=ssl.TLSVersion.TLSv1_2)

    assert seen["check_hostname"] is False
    assert seen["verify_mode"] == ssl.CERT_NONE
    assert result == {"status": "connected", "detail": ""}


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


# ---------------------------------------------------------------------------
# Assertion-branch tests for the two @then steps
# ---------------------------------------------------------------------------


from vip_tests.cross_product.test_ssl import (  # noqa: E402
    modern_tls_succeeds,
    old_tls_rejected,
)


def _results(tls1_0, tls1_1, tls1_2):
    return {
        "tls1_0": tls1_0,
        "tls1_1": tls1_1,
        "tls1_2": tls1_2,
    }


def test_old_tls_rejected_passes_when_both_refused():
    results = _results(
        {"status": "rejected", "detail": "unsupported protocol"},
        {"status": "rejected", "detail": "unsupported protocol"},
        {"status": "connected", "detail": ""},
    )
    old_tls_rejected(results)  # no assertion error


def test_old_tls_rejected_fails_on_connected_tls_1_0():
    results = _results(
        {"status": "connected", "detail": ""},
        {"status": "rejected", "detail": ""},
        {"status": "connected", "detail": ""},
    )
    with pytest.raises(AssertionError) as info:
        old_tls_rejected(results)
    msg = str(info.value)
    assert "TLS 1.0" in msg
    assert "Legacy TLS" in msg


def test_old_tls_rejected_fails_on_cert_verify_for_legacy_version():
    results = _results(
        {"status": "rejected", "detail": ""},
        {
            "status": "cert_verify_failed",
            "detail": "[SSL: CERTIFICATE_VERIFY_FAILED] ...",
        },
        {"status": "connected", "detail": ""},
    )
    with pytest.raises(AssertionError) as info:
        old_tls_rejected(results)
    msg = str(info.value)
    assert "TLS 1.1" in msg
    assert "Legacy TLS" in msg
    assert "cert verification" in msg


def test_modern_tls_succeeds_passes_when_connected():
    results = _results(
        {"status": "rejected", "detail": ""},
        {"status": "rejected", "detail": ""},
        {"status": "connected", "detail": ""},
    )
    modern_tls_succeeds(results)  # no assertion error


def test_modern_tls_succeeds_surfaces_cert_verify_with_guidance():
    results = _results(
        {"status": "rejected", "detail": ""},
        {"status": "rejected", "detail": ""},
        {
            "status": "cert_verify_failed",
            "detail": "[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer",
        },
    )
    with pytest.raises(AssertionError) as info:
        modern_tls_succeeds(results)
    msg = str(info.value)
    assert "certificate-trust issue" in msg
    assert "SSL_CERT_FILE" in msg
    assert "certifi" in msg
    assert "CERTIFICATE_VERIFY_FAILED" in msg


def test_modern_tls_succeeds_reports_plain_rejection_clearly():
    results = _results(
        {"status": "rejected", "detail": ""},
        {"status": "rejected", "detail": ""},
        {"status": "rejected", "detail": "unsupported protocol"},
    )
    with pytest.raises(AssertionError) as info:
        modern_tls_succeeds(results)
    msg = str(info.value)
    assert "TLS 1.2 connection failed" in msg
    assert "unsupported protocol" in msg


def test_modern_tls_succeeds_insecure_cert_failure_does_not_suggest_ssl_cert_file():
    """Under ``tls.insecure=true`` a cert-verify failure should not blame the
    user for skipping a step they explicitly opted out of. #457."""
    results = _results(
        {"status": "rejected", "detail": ""},
        {"status": "rejected", "detail": ""},
        {
            "status": "cert_verify_failed",
            "detail": "self-signed certificate",
        },
    )
    results["insecure"] = True
    with pytest.raises(AssertionError) as info:
        modern_tls_succeeds(results)
    msg = str(info.value)
    assert "SSL_CERT_FILE" not in msg
    assert "tls.insecure=true" in msg
    assert "self-signed certificate" in msg


# ---------------------------------------------------------------------------
# check_ssl_cert connect-vs-handshake exception narrowing #555
# ---------------------------------------------------------------------------


def test_check_ssl_cert_skips_on_connect_failure(monkeypatch):
    """A TCP connect failure (refused/timeout/DNS) means the host is
    unreachable -- not a certificate finding -- so it must still skip."""
    _patch_connect(monkeypatch, OSError("connection refused"))
    vip_config = VIPConfig(connect=ConnectConfig(url="https://connect.example.com"))

    with pytest.raises(pytest.skip.Exception):
        check_ssl_cert("Connect", vip_config)


def test_check_ssl_cert_propagates_non_cert_handshake_errors(monkeypatch):
    """A handshake failure for a reason other than certificate verification
    (e.g. a protocol mismatch) must fail loudly, not be silently skipped --
    a broad skip here would gate the expiry-margin assertion behind "not
    applicable" instead of "unknown"."""
    _patch_connect(monkeypatch)
    _patch_handshake(monkeypatch, ssl.SSLError("unsupported protocol"))
    vip_config = VIPConfig(connect=ConnectConfig(url="https://connect.example.com"))

    with pytest.raises(ssl.SSLError, match="unsupported protocol"):
        check_ssl_cert("Connect", vip_config)


# ---------------------------------------------------------------------------
# Certificate-expiry margin ("the certificate is valid and not expired") #555
# ---------------------------------------------------------------------------


def _cert_with_days_remaining(days: float) -> dict:
    expires = datetime.now(timezone.utc) + timedelta(days=days)
    # OpenSSL's notAfter format, e.g. "Jun 15 12:00:00 2030 GMT". A two-digit
    # day sidesteps the single-digit-day double-space quirk (" 1" vs "01").
    return {"notAfter": expires.strftime("%b %d %H:%M:%S %Y GMT")}


def test_cert_expires_at_parses_notafter():
    expires_at = _cert_expires_at({"notAfter": "Jun 15 12:00:00 2030 GMT"})
    assert expires_at == datetime(2030, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_cert_expires_at_handles_single_digit_day_double_space():
    """OpenSSL pads a single-digit day with an extra space instead of
    zero-padding it (e.g. "Jun  1 ..."), not "Jun 01 ...". #560."""
    expires_at = _cert_expires_at({"notAfter": "Jun  1 12:00:00 2030 GMT"})
    assert expires_at == datetime(2030, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "month_abbr,month_num",
    [
        ("Jan", 1),
        ("Feb", 2),
        ("Mar", 3),
        ("Apr", 4),
        ("May", 5),
        ("Jun", 6),
        ("Jul", 7),
        ("Aug", 8),
        ("Sep", 9),
        ("Oct", 10),
        ("Nov", 11),
        ("Dec", 12),
    ],
)
def test_cert_expires_at_all_month_abbreviations(month_abbr, month_num):
    not_after = f"{month_abbr} 15 12:00:00 2030 GMT"
    expires_at = _cert_expires_at({"notAfter": not_after})
    assert expires_at == datetime(2030, month_num, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_cert_expires_at_locale_independent():
    """``_cert_expires_at`` must not depend on ``LC_TIME``. OpenSSL's
    ``notAfter`` month abbreviation is always English regardless of locale,
    but a ``%b``-based ``strptime`` reads the process's LC_TIME month table
    -- so on a non-English runner (VIP is customer-run software; we don't
    control this) the old implementation raised on this exact, unchanging
    string. #560. Skips (rather than silently passing) if the runner lacks
    the de_DE locale data, since that would prove nothing either way.
    """
    original = locale.setlocale(locale.LC_TIME)
    try:
        try:
            locale.setlocale(locale.LC_TIME, "de_DE.UTF-8")
        except locale.Error:
            pytest.skip("de_DE.UTF-8 locale not available on this runner")

        expires_at = _cert_expires_at({"notAfter": "Jun 15 12:00:00 2030 GMT"})
        assert expires_at == datetime(2030, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    finally:
        # Reset unconditionally so a locale change here can't leak into
        # other tests sharing this worker process.
        locale.setlocale(locale.LC_TIME, original)


def test_cert_valid_passes_when_expiry_beyond_threshold():
    cert_info = {
        "error": None,
        "cert": _cert_with_days_remaining(400),
        "hostname": "example.com",
    }
    cert_valid(cert_info, VIPConfig())  # no assertion error


def test_cert_valid_fails_when_expiry_within_threshold():
    """A soon-to-expire certificate must trip the margin check -- proof the
    assertion isn't vacuous. #555."""
    cert_info = {
        "error": None,
        "cert": _cert_with_days_remaining(5),
        "hostname": "example.com",
    }
    with pytest.raises(AssertionError) as info:
        cert_valid(cert_info, VIPConfig())
    msg = str(info.value)
    assert "example.com" in msg
    assert "expires in" in msg
    assert "30-day" in msg


def test_cert_valid_respects_configured_threshold():
    cert_info = {
        "error": None,
        "cert": _cert_with_days_remaining(10),
        "hostname": "example.com",
    }
    # 10 days remaining clears a 5-day threshold...
    cert_valid(cert_info, VIPConfig(cert_expiry_warning_days=5))
    # ...but not the 30-day default.
    with pytest.raises(AssertionError):
        cert_valid(cert_info, VIPConfig())


# ---------------------------------------------------------------------------
# "the HTTP port is closed or serves no content directly" #555
# ---------------------------------------------------------------------------


def test_http_port_no_content_passes_when_port_closed():
    http_port_no_content({"error": "port_closed", "status": None})  # no assertion error


def test_http_port_no_content_passes_on_redirect():
    http_port_no_content({"error": None, "status": 301})  # no assertion error


def test_http_port_no_content_fails_on_real_content():
    """A plain-HTTP server answering with real content (not a redirect) must
    trip this step -- proof it isn't a vacuous ``pass`` anymore. #555."""
    with pytest.raises(AssertionError) as info:
        http_port_no_content({"error": None, "status": 200})
    assert "served content directly" in str(info.value)


# ---------------------------------------------------------------------------
# request_http transport-error classification #457
# ---------------------------------------------------------------------------


def test_request_http_classifies_protocol_error_as_port_closed(monkeypatch):
    """A plaintext request landing on a TLS-only port raises a protocol
    error, not ``httpx.ConnectError`` -- it must still classify as
    "port_closed" so the redirect / no-content checks treat a missing
    plain-HTTP listener as acceptable rather than failing. #457."""

    def fake_get(url, follow_redirects=False, timeout=10, **kwargs):
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.")

    monkeypatch.setattr(httpx, "get", fake_get)
    vip_config = VIPConfig(connect=ConnectConfig(url="https://connect.example.com"))

    result = request_http("Connect", vip_config)

    assert result["error"] == "port_closed"


def test_request_http_classifies_read_error_as_port_closed(monkeypatch):
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
    vip_config = VIPConfig(connect=ConnectConfig(url="https://connect.example.com"))

    result = request_http("Connect", vip_config)

    assert result["error"] == "port_closed"


def test_request_http_does_not_swallow_unrelated_exceptions(monkeypatch):
    """A regression guard for the failure mode this whole file exists to
    prevent: classifying every exception as "port_closed" would make
    ``redirects_to_https`` and ``http_port_no_content`` both pass silently
    on a malformed URL or a code bug, not just on a genuinely closed port.
    ``httpx.InvalidURL`` derives directly from ``Exception`` (not
    ``httpx.HTTPError``), so it must still propagate rather than being
    classified as "port_closed". #457.
    """

    def fake_get(url, follow_redirects=False, timeout=10, **kwargs):
        raise httpx.InvalidURL("Invalid URL component 'host'")

    monkeypatch.setattr(httpx, "get", fake_get)
    vip_config = VIPConfig(connect=ConnectConfig(url="https://connect.example.com"))

    with pytest.raises(httpx.InvalidURL):
        request_http("Connect", vip_config)


def test_request_http_does_not_swallow_programming_errors(monkeypatch):
    """A plain bug (e.g. a typo introduced in a future edit) must not be
    reported as an acceptable "port closed" outcome either. #457."""

    def fake_get(url, follow_redirects=False, timeout=10, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(httpx, "get", fake_get)
    vip_config = VIPConfig(connect=ConnectConfig(url="https://connect.example.com"))

    with pytest.raises(RuntimeError, match="boom"):
        request_http("Connect", vip_config)


def test_request_http_does_not_classify_connect_timeout_as_port_closed(monkeypatch):
    """A timeout is not "no plain-HTTP listener" -- it means the host is
    filtered (SYN dropped) or hung, a materially different, reportable
    state from a genuinely closed port. ``httpx.ConnectTimeout`` is a
    ``TimeoutException``, NOT an ``httpx.NetworkError``/``ProtocolError``,
    so the narrow except must let it propagate rather than silently passing
    the redirect/no-content checks. #457.
    """

    def fake_get(url, follow_redirects=False, timeout=10, **kwargs):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx, "get", fake_get)
    vip_config = VIPConfig(connect=ConnectConfig(url="https://connect.example.com"))

    with pytest.raises(httpx.ConnectTimeout):
        request_http("Connect", vip_config)


def test_request_http_does_not_classify_read_timeout_as_port_closed(monkeypatch):
    """A ``ReadTimeout`` means the port accepted the connection and then
    never answered -- a hung listener, a real bug worth surfacing loudly,
    not "port closed". #457."""

    def fake_get(url, follow_redirects=False, timeout=10, **kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(httpx, "get", fake_get)
    vip_config = VIPConfig(connect=ConnectConfig(url="https://connect.example.com"))

    with pytest.raises(httpx.ReadTimeout):
        request_http("Connect", vip_config)
