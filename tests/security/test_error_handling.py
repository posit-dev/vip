"""Step definitions for API error-handling tests.

These tests verify that the Connect API returns the correct HTTP status codes
for unauthenticated requests, invalid credentials, and non-existent endpoints.
Raw httpx is used intentionally to avoid the auth baked into the API clients.
"""

from __future__ import annotations

import httpx
from pytest_bdd import scenarios, then, when

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

scenarios("test_error_handling.feature")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A Connect endpoint that requires authentication.
_AUTHED_ENDPOINT = "/__api__/v1/content"

# A path that does not exist on any Posit product.
_MISSING_ENDPOINT = "/__api__/v1/does-not-exist-vip-test"


# ---------------------------------------------------------------------------
# Steps - unauthenticated request
# ---------------------------------------------------------------------------


@when("I make an unauthenticated API request to Connect", target_fixture="unauthed_response")
def make_unauthed_request(vip_config):
    url = vip_config.connect.url.rstrip("/") + _AUTHED_ENDPOINT
    resp = httpx.get(url, timeout=15)
    return resp


@then("the response status is 401")
def status_is_401(unauthed_response):
    assert unauthed_response.status_code == 401, (
        f"Expected HTTP 401, got {unauthed_response.status_code}"
    )


# ---------------------------------------------------------------------------
# Steps - invalid API key
# ---------------------------------------------------------------------------


@when("I make an API request to Connect with an invalid key", target_fixture="bad_key_response")
def make_bad_key_request(vip_config):
    url = vip_config.connect.url.rstrip("/") + _AUTHED_ENDPOINT
    resp = httpx.get(url, headers={"Authorization": "Key vip-invalid-key-00000"}, timeout=15)
    return resp


@then("the response status is 401")
def status_is_401_bad_key(bad_key_response):
    assert bad_key_response.status_code == 401, (
        f"Expected HTTP 401, got {bad_key_response.status_code}"
    )


# ---------------------------------------------------------------------------
# Steps - non-existent endpoint
# ---------------------------------------------------------------------------


@when("I request a non-existent endpoint on Connect", target_fixture="missing_response")
def request_missing_endpoint(vip_config):
    url = vip_config.connect.url.rstrip("/") + _MISSING_ENDPOINT
    resp = httpx.get(url, timeout=15)
    return resp


@then("the response status is 404")
def status_is_404(missing_response):
    assert missing_response.status_code == 404, (
        f"Expected HTTP 404, got {missing_response.status_code}"
    )
