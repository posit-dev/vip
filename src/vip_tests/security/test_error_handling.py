"""Step definitions for API error-handling tests.

These tests verify that the Connect API returns the correct HTTP status codes
for unauthenticated requests, invalid credentials, and non-existent endpoints.
Raw httpx is used intentionally to avoid the auth baked into the API clients.
"""

from __future__ import annotations

import httpx
from pytest_bdd import scenarios, then, when

from vip.http_semantics import denied_by_external_gateway

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


@when("I make an unauthenticated API request to Connect", target_fixture="api_response")
def make_unauthed_request(vip_config):
    url = vip_config.connect.url.rstrip("/") + _AUTHED_ENDPOINT
    resp = httpx.get(url, timeout=15, verify=vip_config.verify)
    return resp


# ---------------------------------------------------------------------------
# Steps - invalid API key
# ---------------------------------------------------------------------------


@when("I make an API request to Connect with an invalid key", target_fixture="api_response")
def make_bad_key_request(vip_config):
    url = vip_config.connect.url.rstrip("/") + _AUTHED_ENDPOINT
    resp = httpx.get(
        url,
        headers={"Authorization": "Key vip-invalid-key-00000"},
        timeout=15,
        verify=vip_config.verify,
    )
    return resp


# ---------------------------------------------------------------------------
# Steps - non-existent endpoint
# ---------------------------------------------------------------------------


@when("I request a non-existent endpoint on Connect", target_fixture="api_response")
def request_missing_endpoint(vip_config):
    url = vip_config.connect.url.rstrip("/") + _MISSING_ENDPOINT
    resp = httpx.get(url, timeout=15, verify=vip_config.verify)
    return resp


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


@then("the response status is 401")
def status_is_401(api_response):
    # An OIDC/SSO forward-auth gateway (e.g. Okta proxy) intercepts
    # unauthenticated requests and 307-redirects to its IdP login page before
    # Connect can reply 401.  That redirect is equally "access denied" from
    # VIP's perspective, so we accept it as a valid outcome.
    if denied_by_external_gateway(api_response):
        return
    assert api_response.status_code == 401, f"Expected HTTP 401, got {api_response.status_code}"


@then("the response status is 404")
def status_is_404(api_response):
    # An OIDC/SSO forward-auth gateway intercepts the request before Connect
    # has a chance to return 404; a cross-host redirect is accepted here too.
    if denied_by_external_gateway(api_response):
        return
    assert api_response.status_code == 404, f"Expected HTTP 404, got {api_response.status_code}"
