"""Step definitions for login and page load time tests."""

from __future__ import annotations

import time

import httpx
import pytest
from pytest_bdd import scenarios, then, when

scenarios("test_login_load_times.feature")


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

_LOGIN_PATHS = {
    "Connect": "/__login__",
    "Workbench": "",
    "Package Manager": "",
}


@when("I measure the <product> login page load time", target_fixture="load_time")
def measure_load_time(product, vip_config, performance_config):
    product_key = product.lower().replace(" ", "_")
    pc = vip_config.product_config(product_key)
    if not pc.is_configured:
        pytest.skip(f"{product} is not configured")
    path = _LOGIN_PATHS[product]
    start = time.monotonic()
    resp = httpx.get(
        f"{pc.url}{path}",
        follow_redirects=True,
        timeout=performance_config.page_load_timeout * 3,
    )
    elapsed = time.monotonic() - start
    resp.raise_for_status()
    return elapsed


@then("the page loads in under 10 seconds")
def load_time_ok(load_time, performance_config):
    threshold = performance_config.page_load_timeout
    assert load_time < threshold, f"Page load took {load_time:.2f}s (threshold: {threshold}s)"
