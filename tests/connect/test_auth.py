"""Step definitions for Connect authentication tests."""

from __future__ import annotations

import pytest
from pytest_bdd import scenario, given, when, then


@scenario("test_auth.feature", "User can log in via the web UI")
def test_connect_login_ui():
    pass


@scenario("test_auth.feature", "API key authentication works")
def test_connect_login_api():
    pass


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

@given("Connect is accessible at the configured URL")
def connect_accessible(connect_client):
    assert connect_client is not None, "Connect client not configured"
    status = connect_client.server_status()
    assert status < 400, f"Connect returned HTTP {status}"


@given("a valid API key is configured")
def api_key_configured(vip_config):
    assert vip_config.connect.api_key, (
        "VIP_CONNECT_API_KEY is not set. Set it in vip.toml or as an environment variable."
    )


@when("a user navigates to the Connect login page")
def navigate_to_login(page, connect_url):
    page.goto(f"{connect_url}/__login__")


@when("enters valid credentials")
def enter_credentials(page, test_username, test_password):
    page.fill("[name='username'], #username", test_username)
    page.fill("[name='password'], #password", test_password)
    page.click("button[type='submit']")
    page.wait_for_load_state("networkidle")


@then("the user is successfully authenticated")
def user_authenticated(page, connect_url):
    # After login, should not be on the login page anymore.
    assert "/__login__" not in page.url, "Still on the login page after submitting credentials"


@then("the Connect dashboard is displayed")
def dashboard_displayed(page):
    # The dashboard should have loaded - check for common elements.
    page.wait_for_selector("body", timeout=10000)
    assert page.title(), "Page has no title after login"


@when("I request the current user via the API", target_fixture="api_user")
def request_current_user(connect_client):
    return connect_client.current_user()


@then("the API returns user information")
def api_returns_user(api_user):
    assert "username" in api_user, f"API response missing 'username': {api_user}"
    assert api_user["username"], "API returned empty username"
