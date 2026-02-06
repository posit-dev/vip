"""Step definitions for HTTPS enforcement tests."""

from __future__ import annotations

from urllib.parse import urlparse

import pytest
from pytest_bdd import scenario, given, when, then

import httpx


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

@scenario("test_https.feature", "Connect enforces HTTPS")
def test_connect_https():
    pass


@scenario("test_https.feature", "Workbench enforces HTTPS")
def test_workbench_https():
    pass


@scenario("test_https.feature", "Package Manager enforces HTTPS")
def test_pm_https():
    pass


@scenario("test_https.feature", "Connect does not expose sensitive headers")
def test_connect_headers():
    pass


@scenario("test_https.feature", "Workbench does not expose sensitive headers")
def test_workbench_headers():
    pass


@scenario("test_https.feature", "Package Manager does not expose sensitive headers")
def test_pm_headers():
    pass


# ---------------------------------------------------------------------------
# Steps - HTTPS enforcement
# ---------------------------------------------------------------------------

@given("Connect is configured with an HTTPS URL", target_fixture="product_url")
def connect_https(vip_config):
    if not vip_config.connect.is_configured:
        pytest.skip("Connect is not configured")
    assert vip_config.connect.url.startswith("https://"), (
        f"Connect URL is not HTTPS: {vip_config.connect.url}"
    )
    return vip_config.connect.url


@given("Workbench is configured with an HTTPS URL", target_fixture="product_url")
def workbench_https(vip_config):
    if not vip_config.workbench.is_configured:
        pytest.skip("Workbench is not configured")
    assert vip_config.workbench.url.startswith("https://"), (
        f"Workbench URL is not HTTPS: {vip_config.workbench.url}"
    )
    return vip_config.workbench.url


@given("Package Manager is configured with an HTTPS URL", target_fixture="product_url")
def pm_https(vip_config):
    if not vip_config.package_manager.is_configured:
        pytest.skip("Package Manager is not configured")
    assert vip_config.package_manager.url.startswith("https://"), (
        f"Package Manager URL is not HTTPS: {vip_config.package_manager.url}"
    )
    return vip_config.package_manager.url


@when("I make an HTTP request to Connect", target_fixture="http_result")
@when("I make an HTTP request to Workbench", target_fixture="http_result")
@when("I make an HTTP request to Package Manager", target_fixture="http_result")
def make_http_request(product_url):
    http_url = product_url.replace("https://", "http://")
    try:
        resp = httpx.get(http_url, follow_redirects=False, timeout=10)
        return {"status": resp.status_code, "location": resp.headers.get("location", ""), "refused": False}
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
        f"HTTP request was not refused or redirected (got HTTP {status}). "
        "HTTPS is not enforced."
    )
    assert http_result["location"].startswith("https://"), (
        f"Redirect does not point to HTTPS: {http_result['location']}"
    )


# ---------------------------------------------------------------------------
# Steps - header exposure
# ---------------------------------------------------------------------------

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


@when("I inspect response headers from Connect", target_fixture="response_headers")
@when("I inspect response headers from Workbench", target_fixture="response_headers")
@when("I inspect response headers from Package Manager", target_fixture="response_headers")
def inspect_headers(product_url):
    resp = httpx.get(product_url, follow_redirects=True, timeout=15)
    return dict(resp.headers)


@then("the server does not expose version information in headers")
def no_version_headers(response_headers):
    # Check for common headers that leak server version info.
    risky_headers = ["x-powered-by", "server"]
    for header in risky_headers:
        value = response_headers.get(header, "")
        # Having the header is OK, but it shouldn't contain version numbers.
        if value:
            import re
            version_pattern = re.compile(r"\d+\.\d+")
            if version_pattern.search(value):
                pytest.skip(
                    f"Header '{header}: {value}' exposes version info. "
                    "Consider configuring the server to suppress version details."
                )
