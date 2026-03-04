"""Step definitions for authentication prerequisite checks."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenario, then


@scenario("test_auth_configured.feature", "Test credentials are provided")
def test_credentials_provided():
    pass


@given("VIP is configured with test user credentials", target_fixture="credentials")
def credentials_available(test_username, test_password, auth_provider, interactive_auth):
    return {
        "username": test_username,
        "password": test_password,
        "auth_provider": auth_provider,
        "interactive_auth": interactive_auth,
    }


@then("the username is not empty")
def username_not_empty(credentials):
    # For OIDC without interactive auth, skip if no username is set
    if credentials["auth_provider"] != "password" and not credentials["interactive_auth"]:
        if not credentials["username"]:
            pytest.skip("OIDC authentication without --interactive-auth requires VIP_TEST_USERNAME")

    assert credentials["username"], (
        "VIP_TEST_USERNAME is not set. Set it in vip.toml or as an environment variable."
    )


@then("the password is not empty")
def password_not_empty(credentials):
    # For OIDC without interactive auth, skip if no password is set
    if credentials["auth_provider"] != "password" and not credentials["interactive_auth"]:
        if not credentials["password"]:
            pytest.skip("OIDC authentication without --interactive-auth requires VIP_TEST_PASSWORD")

    assert credentials["password"], (
        "VIP_TEST_PASSWORD is not set. Set it in vip.toml or as an environment variable."
    )
