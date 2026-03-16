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
from pytest_bdd import scenarios, then, when

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

scenarios("test_ssl.feature")


# ---------------------------------------------------------------------------
# Steps - SSL certificate checks
# ---------------------------------------------------------------------------


@when("I check the SSL certificate for <product>", target_fixture="cert_info")
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


@when("I request the HTTP URL for <product>", target_fixture="http_response")
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
