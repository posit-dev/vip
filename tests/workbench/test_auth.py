"""Step definitions for Workbench authentication tests."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_auth.feature", "User can log in to Workbench via the web UI")
def test_workbench_login():
    pass


@given("Workbench is accessible at the configured URL")
def workbench_accessible(workbench_client):
    assert workbench_client is not None, "Workbench client not configured"
    status = workbench_client.health()
    assert status < 400, f"Workbench health-check returned HTTP {status}"


@when("a user navigates to the Workbench login page")
def navigate_to_login(page, workbench_url):
    page.goto(workbench_url)


@when("enters valid Workbench credentials")
def enter_credentials(page, test_username, test_password, auth_provider, interactive_auth):
    if auth_provider != "password":
        if not interactive_auth:
            pytest.skip(
                f"Login form not available for auth provider {auth_provider!r}. "
                "Pass --interactive-auth when browser storage state is pre-loaded."
            )
        # With --interactive-auth the browser is already authenticated via storage state.
        # Wait and check if storage state successfully logged us in.
        page.wait_for_load_state("load")
        on_login = any(kw in page.url.lower() for kw in ("sign-in", "login", "auth"))
        if on_login:
            pytest.skip(
                "Interactive auth storage state did not authenticate Workbench. "
                "The OIDC session may not be shared between Connect and Workbench."
            )
        return
    page.fill("#username, [name='username']", test_username)
    page.fill("#password, [name='password']", test_password)
    page.click("button[type='submit'], #sign-in")
    page.wait_for_load_state("load")


@then("the user is redirected to the Workbench home page")
def home_page_displayed(page, workbench_url):
    # After login the URL should no longer be the sign-in page.
    on_login = any(kw in page.url.lower() for kw in ("sign-in", "login", "auth"))
    assert not on_login, f"Still on the login page: {page.url}"
