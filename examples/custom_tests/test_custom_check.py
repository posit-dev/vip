"""Example custom test - extend VIP with site-specific checks.

Place this file (and its .feature file) in a directory, then configure VIP to
include it:

    [general]
    extension_dirs = ["/path/to/custom_tests"]

Or on the command line:

    pytest --vip-extensions=/path/to/custom_tests

Custom tests have full access to VIP fixtures (vip_config, connect_client,
etc.) and can use any pytest-bdd or Playwright features.
"""

from __future__ import annotations

import httpx
import pytest
from pytest_bdd import given, scenario, then, when

# The URL to check - replace with your own endpoint.
CUSTOM_ENDPOINT = "https://example.com/health"


@scenario("test_custom_check.feature", "Example custom health check")
def test_custom_health():
    pass


@given("I have a custom endpoint to verify")
def have_endpoint():
    # Replace this with your own precondition logic.
    pass


@when("I request the custom endpoint", target_fixture="custom_response")
def request_endpoint():
    try:
        resp = httpx.get(CUSTOM_ENDPOINT, timeout=15)
        return resp
    except Exception as exc:
        pytest.fail(f"Could not reach {CUSTOM_ENDPOINT}: {exc}")


@then("it responds successfully")
def responds_ok(custom_response):
    assert custom_response.status_code < 400, (
        f"Custom endpoint returned HTTP {custom_response.status_code}"
    )
