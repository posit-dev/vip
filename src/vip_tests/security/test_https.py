"""Step definitions for HTTPS enforcement tests."""

from __future__ import annotations

import re
import ssl

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
    assert pc.url.startswith("https://"), f"{product} URL is not HTTPS: {pc.url}"
    return pc.url


@when(parsers.parse("I make an HTTP request to {product}"), target_fixture="http_result")
def make_http_request(product_url):
    http_url = product_url.replace("https://", "http://")
    try:
        resp = httpx.get(http_url, follow_redirects=False, timeout=10)
        return {
            "status": resp.status_code,
            "location": resp.headers.get("location", ""),
            "refused": False,
        }
    except httpx.ConnectError:
        return {"status": None, "location": "", "refused": True}
    except Exception:
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
        resp = httpx.get(pc.url, follow_redirects=True, timeout=15)
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


@then("the server does not expose version information in headers")
def no_version_headers(response_headers):
    # Check for common headers that leak server version info.
    risky_headers = ["x-powered-by", "server"]
    for header in risky_headers:
        value = response_headers.get(header, "")
        # Having the header is OK, but it shouldn't contain version numbers.
        if value:
            version_pattern = re.compile(r"\d+\.\d+")
            if version_pattern.search(value):
                pytest.fail(
                    f"Header '{header}: {value}' exposes version info. "
                    "Configure the server to suppress version details."
                )
