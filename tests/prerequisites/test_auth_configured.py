"""Step definitions for authentication prerequisite checks."""

from __future__ import annotations

from pytest_bdd import given, scenario, then


@scenario("test_auth_configured.feature", "Test credentials are provided")
def test_credentials_provided():
    pass


@given("VIP is configured with test user credentials", target_fixture="credentials")
def credentials_available(test_username, test_password):
    return {"username": test_username, "password": test_password}


@then("the username is not empty")
def username_not_empty(credentials):
    assert credentials["username"], (
        "VIP_TEST_USERNAME is not set. Set it in vip.toml or as an environment variable."
    )


@then("the password is not empty")
def password_not_empty(credentials):
    assert credentials["password"], (
        "VIP_TEST_PASSWORD is not set. Set it in vip.toml or as an environment variable."
    )
