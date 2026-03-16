"""Step definitions for prerequisite component checks."""

from __future__ import annotations

import httpx
import pytest
from pytest_bdd import parsers, scenarios, then, when

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

scenarios("test_components.feature")


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

_HEALTH_ENDPOINTS = {
    "Connect": "/__api__/server_settings",
    "Workbench": "/health-check",
    "Package Manager": "/__api__/status",
}


@when(parsers.parse("I request the {product} health endpoint"), target_fixture="health_response")
def request_health_endpoint(product, vip_config):
    endpoint = _HEALTH_ENDPOINTS[product]
    product_key = product.lower().replace(" ", "_")
    pc = vip_config.product_config(product_key)
    if not pc.is_configured:
        pytest.skip(f"{product} is not configured")
    resp = httpx.get(f"{pc.url}{endpoint}", timeout=15)
    return resp


@then("the server responds with a successful status code")
def server_responds_ok(health_response):
    assert health_response.status_code < 400, (
        f"Expected success, got HTTP {health_response.status_code}"
    )
