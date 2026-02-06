"""Step definitions for auth policy alignment tests."""

from __future__ import annotations

import pytest
from pytest_bdd import scenario, given, when, then

import httpx


@scenario("test_auth_policy.feature", "Auth provider matches expected configuration")
def test_auth_provider():
    pass


@scenario("test_auth_policy.feature", "Unauthenticated API access is denied")
def test_unauthed_denied():
    pass


@given("the expected auth provider is specified in vip.toml")
def auth_provider_specified(vip_config):
    if not vip_config.auth.provider:
        pytest.skip("No auth provider specified in vip.toml")


@when("I check the auth configuration", target_fixture="auth_info")
def check_auth(vip_config):
    return {"provider": vip_config.auth.provider}


@then("the configured provider matches expectations")
def provider_matches(auth_info):
    assert auth_info["provider"] in ("password", "ldap", "saml", "oidc"), (
        f"Unexpected auth provider: {auth_info['provider']}"
    )


@given("Connect is configured in vip.toml")
def connect_configured(vip_config):
    if not vip_config.connect.is_configured:
        pytest.skip("Connect is not configured")


@when("I make an unauthenticated API request to Connect", target_fixture="unauth_response")
def unauth_request(vip_config):
    resp = httpx.get(
        f"{vip_config.connect.url}/__api__/v1/user",
        timeout=15,
    )
    return resp


@then("the request is rejected with 401 or 403")
def request_rejected(unauth_response):
    assert unauth_response.status_code in (401, 403), (
        f"Unauthenticated request returned HTTP {unauth_response.status_code}; "
        "expected 401 or 403"
    )
