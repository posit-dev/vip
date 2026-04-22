"""Step definitions for login and page load time tests."""

from __future__ import annotations

import time

import httpx
import pytest
from pytest_bdd import parsers, scenarios, then, when

scenarios("test_login_load_times.feature")


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

_LOGIN_PATHS = {
    "Connect": "/__login__",
    "Workbench": "",
    "Package Manager": "",
}


@when(parsers.parse("I measure the {product} login page load time"), target_fixture="load_time")
def measure_load_time(product, vip_config, performance_config):
    product_key = product.lower().replace(" ", "_")
    pc = vip_config.product_config(product_key)
    if not pc.is_configured:
        pytest.skip(f"{product} is not configured")
    path = _LOGIN_PATHS[product]
    url = f"{pc.url}{path}"
    try:
        start = time.monotonic()
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=performance_config.page_load_timeout * 3,
        )
        elapsed = time.monotonic() - start
    except (httpx.ConnectError, httpx.ProxyError, httpx.ConnectTimeout) as exc:
        # Connectivity problem between the test runner and the product URL
        # (proxy/firewall/DNS/closed port) is not a login-performance finding.
        # We catch exactly these three pre-connect failures (not the broader
        # httpx.TransportError) so that mid-transfer errors like ReadError or
        # ReadTimeout still surface as hard failures rather than silently skipping.
        # Reachability itself is already verified by the prerequisites suite
        # (test_components.py), so a skip here avoids double-reporting.
        pytest.skip(
            f"{product} login URL not reachable from test runner "
            f"({url}): {exc}. Check network path, proxy configuration, "
            "DNS resolution, and that the port is open from the runner."
        )
    resp.raise_for_status()
    return elapsed


@then("the page loads within the configured timeout")
def load_time_ok(load_time, performance_config):
    threshold = performance_config.page_load_timeout
    assert load_time < threshold, f"Page load took {load_time:.2f}s (threshold: {threshold}s)"
