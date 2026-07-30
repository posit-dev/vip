"""Step definitions for HTTPS enforcement tests."""

from __future__ import annotations

import re
import ssl
import warnings

import httpx
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

scenarios("test_https.feature")


# ---------------------------------------------------------------------------
# Shared diagnostic text
# ---------------------------------------------------------------------------

# CA-bundle guidance reused in the cert-verification skip below.
# src/vip_tests/cross_product/test_ssl.py has a similar message in the
# ``modern_tls_succeeds`` step — keep the two in sync when updating guidance.
_CERT_TRUST_HINT = (
    "This is a certificate-trust issue on the test runner, not a "
    "server security finding. If the server uses a valid public "
    "certificate (e.g. behind an AWS ALB with an ACM cert), set "
    "SSL_CERT_FILE to a CA bundle that includes public roots: "
    "/etc/ssl/certs/ca-certificates.crt on Debian/Ubuntu, "
    "/etc/pki/tls/certs/ca-bundle.crt on RHEL, or the path "
    "produced by `python -m certifi`."
)


# ---------------------------------------------------------------------------
# Steps - HTTPS enforcement
# ---------------------------------------------------------------------------


@given(parsers.parse("{product} is configured with an HTTPS URL"), target_fixture="product_url")
def product_configured_https(product, vip_config):
    product_key = product.lower().replace(" ", "_")
    pc = vip_config.product_config(product_key)
    if not pc.is_configured:
        pytest.skip(f"{product} is not configured")
    if not pc.url.startswith("https://"):
        # HTTP-only deployments (e.g. ephemeral test instances with
        # tls.insecure=true) cannot enforce HTTPS — not a finding. See #268.
        pytest.skip(f"{product} URL is not HTTPS: {pc.url}")
    return pc.url


@when(parsers.parse("I make an HTTP request to {product}"), target_fixture="http_result")
def make_http_request(product_url, vip_config):
    http_url = product_url.replace("https://", "http://")
    try:
        resp = httpx.get(http_url, follow_redirects=False, timeout=10, verify=vip_config.verify)
        return {
            "status": resp.status_code,
            "location": resp.headers.get("location", ""),
            "refused": False,
        }
    except (httpx.NetworkError, httpx.ProtocolError):
        # NetworkError (ConnectError/ReadError/WriteError/CloseError) is a
        # refused, reset, or closed TCP connection; ProtocolError (its
        # subclass RemoteProtocolError in particular) is what a plaintext
        # HTTP request gets back from a TLS-only port. Both mean "no usable
        # plain-HTTP endpoint" for the check below. In practice, hitting a
        # TLS-only port with plaintext HTTP has been observed to raise
        # EITHER RemoteProtocolError OR ReadError/"Connection reset by
        # peer" depending on the server and OS -- confirmed against a live
        # self-signed server, not assumed -- so NetworkError, not just
        # ConnectError, is needed.
        #
        # Deliberately NOT ``httpx.HTTPError`` (too wide) or a bare
        # ``except Exception`` (which this used to be, pre-#457, and is
        # wider still): a timeout means the host is filtered or hung, a
        # materially different, reportable state -- not "closed" -- so it
        # must fall through and fail loudly. An unrelated bug -- a
        # malformed configured URL raising httpx.InvalidURL, or a future
        # edit introducing a NameError/AttributeError here -- must
        # propagate as a real failure too, not get reported as "port
        # closed, that's fine". A silent "refused" on any exception is
        # exactly the vacuous-check failure mode #555 exists to remove.
        # src/vip_tests/cross_product/test_ssl.py::request_http classifies
        # its sibling check the same narrow way -- keep the two in sync.
        return {"status": None, "location": "", "refused": True}


@then("the connection is refused or redirected to HTTPS")
def https_enforced(http_result):
    if http_result["refused"]:
        return  # HTTP port closed - good.
    status = http_result["status"]
    assert status in (301, 302, 307, 308), (
        f"HTTP request was not refused or redirected (got HTTP {status}). HTTPS is not enforced."
    )
    assert http_result["location"].startswith("https://"), (
        f"Redirect does not point to HTTPS: {http_result['location']}"
    )


# ---------------------------------------------------------------------------
# Steps - header exposure
# ---------------------------------------------------------------------------


@when(parsers.parse("I inspect response headers from {product}"), target_fixture="response_headers")
def inspect_headers(product, vip_config):
    product_key = product.lower().replace(" ", "_")
    pc = vip_config.product_config(product_key)
    if not pc.is_configured:
        pytest.skip(f"{product} is not configured")

    try:
        resp = httpx.get(pc.url, follow_redirects=True, timeout=15, verify=vip_config.verify)
    except httpx.ConnectError as exc:
        # httpx wraps ssl.SSLCertVerificationError in httpx.ConnectError.
        # A cert-verification failure is a trust-bundle issue on the test
        # runner (e.g. missing public roots when fronted by an ALB with an
        # ACM cert), not a server security finding — skip with clear
        # guidance rather than failing as "connection refused".
        # src/vip_tests/cross_product/test_ssl.py applies the same cert-trust
        # classification; it raises there because that test is specifically
        # about TLS enforcement, whereas here we skip because the test is
        # about response headers, not certificate validity.
        # Primary check: httpx sets __cause__ to ssl.SSLCertVerificationError when
        # the TLS handshake fails due to certificate verification.  String fallback
        # covers transports where httpx does not populate __cause__ but still
        # surfaces the OpenSSL error token in the exception message.
        cause = exc.__cause__
        if isinstance(cause, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(
            exc
        ):
            pytest.skip(
                f"Could not verify TLS certificate for {product} at {pc.url}: {exc}. "
                + _CERT_TRUST_HINT
            )
        pytest.fail(
            f"Could not reach {product} at {pc.url}: connection refused. "
            "Check firewall rules, proxy configuration, DNS resolution, and port. "
            "This is a connectivity issue, not a security finding."
        )
    return dict(resp.headers)


@then("any version information in response headers is reported")
def no_version_headers(response_headers):
    """Report version disclosure in response headers; fail only where it is
    fixable at the source.

    Both headers below leak a version, but they are not the same finding:

    ``server`` is the product identifying itself -- Package Manager sends
    ``Posit Package Manager v2026.06.0`` and offers no setting to suppress it,
    so the only remediation is stripping it at the reverse proxy in front. A
    check that fails on every stock Posit deployment, with advice the product
    can't satisfy, is noise: it turns the whole security category red by
    default and teaches people to skim past it. Warn instead, so the exposure
    is still on the record for a hardening baseline that forbids it.

    ``x-powered-by`` is a real finding. No Posit product sets it, so its
    presence means a reverse proxy or app server in front is disclosing its
    own version -- and that is configurable exactly where it originates. This
    stays fatal, which is also what keeps this check from being vacuous: a
    warning-only check can never fail, and a check that can never fail is not
    a check (#555).
    """
    version_pattern = re.compile(r"\d+\.\d+")

    server = response_headers.get("server", "")
    if server and version_pattern.search(server):
        warnings.warn(
            f"VIP: response header 'server: {server}' discloses a version number. "
            "Posit products emit this themselves and have no setting to suppress it — "
            "strip or rewrite the header at the reverse proxy in front of the "
            "deployment (nginx: `proxy_hide_header Server`) if your hardening "
            "baseline forbids version disclosure.",
            stacklevel=2,
        )

    powered_by = response_headers.get("x-powered-by", "")
    if powered_by and version_pattern.search(powered_by):
        pytest.fail(
            f"Header 'x-powered-by: {powered_by}' exposes version info. No Posit "
            "product sets this header, so it comes from a reverse proxy or "
            "application server in front of the deployment. Suppress it there "
            "(nginx: `proxy_hide_header X-Powered-By`; Express: "
            "`app.disable('x-powered-by')`)."
        )
