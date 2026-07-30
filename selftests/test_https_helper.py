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

import warnings

import httpx
import pytest
from _pytest.outcomes import Failed

from vip.config import VIPConfig
from vip_tests.security.test_https import make_http_request, no_version_headers


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


# ---------------------------------------------------------------------------
# no_version_headers: version disclosure in response headers
# ---------------------------------------------------------------------------


class TestNoVersionHeaders:
    """Version disclosure is reported, but only ``x-powered-by`` fails.

    Package Manager emits ``server: Posit Package Manager v2026.06.0`` itself
    and offers no setting to suppress it, so failing on it made the security
    category permanently red on every stock deployment with advice nobody
    could act on -- a finding that fires unconditionally trains people to
    ignore the whole category.

    ``x-powered-by`` is different: no Posit product sets it, so seeing one
    means a reverse proxy or app server in front of the deployment is leaking
    its own version, which *is* configurable where it originates. Keeping that
    one fatal is what stops this check from becoming vacuous (#555).
    """

    def test_product_server_header_with_version_warns_instead_of_failing(self):
        headers = {"server": "Posit Package Manager v2026.06.0"}

        with pytest.warns(UserWarning, match=r"2026\.06\.0"):
            no_version_headers(headers)

    def test_warning_names_the_product_and_the_remediation(self):
        headers = {"server": "Posit Package Manager v2026.06.0"}

        with pytest.warns(UserWarning) as record:
            no_version_headers(headers)

        message = str(record[0].message)
        assert "server" in message
        assert "proxy" in message.lower(), (
            f"warning must point at the only place this can be stripped: {message}"
        )

    def test_x_powered_by_with_version_still_fails(self):
        """A fronting proxy leaking its version is actionable where it is set,
        so it stays a failure -- otherwise this check can never fail at all."""
        headers = {"x-powered-by": "Express/4.18.2"}

        with pytest.raises(Failed, match="x-powered-by"):
            no_version_headers(headers)

    def test_versionless_server_header_neither_warns_nor_fails(self):
        """``server: nginx`` discloses no version -- nothing to report."""
        headers = {"server": "nginx"}

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            no_version_headers(headers)

    def test_absent_headers_neither_warn_nor_fail(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            no_version_headers({})

    def test_both_headers_present_fails_on_the_actionable_one(self):
        """The fatal finding must not be masked by the warned-about one."""
        headers = {
            "server": "Posit Package Manager v2026.06.0",
            "x-powered-by": "Express/4.18.2",
        }

        with pytest.warns(UserWarning), pytest.raises(Failed, match="x-powered-by"):
            no_version_headers(headers)
