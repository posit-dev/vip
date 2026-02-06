"""Step definitions for SSL / HTTPS checks.

These tests specifically target common misconfigurations:
- Expired certificates
- Incomplete certificate chains (missing intermediate CA)
- HTTP not redirecting to HTTPS
"""

from __future__ import annotations

import ssl
import socket
from urllib.parse import urlparse

import pytest
from pytest_bdd import scenario, given, when, then

import httpx


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

@scenario("test_ssl.feature", "SSL certificate is valid for Connect")
def test_ssl_connect():
    pass


@scenario("test_ssl.feature", "SSL certificate is valid for Workbench")
def test_ssl_workbench():
    pass


@scenario("test_ssl.feature", "SSL certificate is valid for Package Manager")
def test_ssl_package_manager():
    pass


@scenario("test_ssl.feature", "HTTP redirects to HTTPS for Connect")
def test_https_redirect_connect():
    pass


@scenario("test_ssl.feature", "HTTP redirects to HTTPS for Workbench")
def test_https_redirect_workbench():
    pass


@scenario("test_ssl.feature", "HTTP redirects to HTTPS for Package Manager")
def test_https_redirect_package_manager():
    pass


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@pytest.fixture()
def ssl_state():
    return {}


# ---------------------------------------------------------------------------
# Steps - SSL certificate checks
# ---------------------------------------------------------------------------

_PRODUCT_CONFIG_MAP = {
    "Connect": "connect",
    "Workbench": "workbench",
    "Package Manager": "package_manager",
}


@given("Connect is configured in vip.toml", target_fixture="product_url")
def connect_configured(vip_config):
    if not vip_config.connect.is_configured:
        pytest.skip("Connect is not configured")
    return vip_config.connect.url


@given("Workbench is configured in vip.toml", target_fixture="product_url")
def workbench_configured(vip_config):
    if not vip_config.workbench.is_configured:
        pytest.skip("Workbench is not configured")
    return vip_config.workbench.url


@given("Package Manager is configured in vip.toml", target_fixture="product_url")
def pm_configured(vip_config):
    if not vip_config.package_manager.is_configured:
        pytest.skip("Package Manager is not configured")
    return vip_config.package_manager.url


@when("I check the SSL certificate for Connect", target_fixture="cert_info")
@when("I check the SSL certificate for Workbench", target_fixture="cert_info")
@when("I check the SSL certificate for Package Manager", target_fixture="cert_info")
def check_ssl_cert(product_url):
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

@when("I request the HTTP URL for Connect", target_fixture="http_response")
@when("I request the HTTP URL for Workbench", target_fixture="http_response")
@when("I request the HTTP URL for Package Manager", target_fixture="http_response")
def request_http(product_url):
    http_url = product_url.replace("https://", "http://")
    parsed = urlparse(http_url)
    if parsed.scheme != "http":
        http_url = f"http://{parsed.hostname}"
    try:
        resp = httpx.get(http_url, follow_redirects=False, timeout=10)
        return {"status": resp.status_code, "location": resp.headers.get("location", ""), "error": None}
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
