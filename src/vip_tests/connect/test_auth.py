"""Step definitions for Connect authentication tests."""

from __future__ import annotations

import pytest
from pytest_bdd import scenario, then, when


@scenario("test_auth.feature", "User can log in via the web UI")
def test_connect_login_ui():
    pass


@scenario("test_auth.feature", "API key authentication works")
def test_connect_login_api():
    pass


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@when("a user navigates to the Connect login page")
def navigate_to_login(page, connect_url):
    page.goto(f"{connect_url}/__login__")


@when("enters valid credentials")
def enter_credentials(page, test_username, test_password, auth_provider, interactive_auth):
    if interactive_auth:
        # With --interactive-auth the browser is already authenticated via storage
        # state. The login page will redirect immediately — wait for the URL to
        # leave /__login__ rather than relying on networkidle, which can fire
        # before a JS-triggered redirect completes.
        page.wait_for_url(lambda url: "/__login__" not in url, timeout=10000)
        return
    if auth_provider != "password":
        pytest.skip(
            f"Login form not available for auth provider {auth_provider!r}. "
            "Pass --interactive-auth when browser storage state is pre-loaded."
        )
    if not test_username or not test_password:
        pytest.fail(
            "UI login test requires VIP_TEST_USERNAME and VIP_TEST_PASSWORD "
            "to be set when auth_provider is 'password'."
        )
    page.fill("[name='username'], #username", test_username)
    page.fill("[name='password'], #password", test_password)
    page.click("[data-automation='login-panel-submit']")
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
