"""Step definitions for Workbench authentication tests."""

from __future__ import annotations

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
def enter_credentials(page, test_username, test_password):
    page.fill("#username, [name='username']", test_username)
    page.fill("#password, [name='password']", test_password)
    page.click("button[type='submit'], #sign-in")
    page.wait_for_load_state("networkidle")


@then("the user is redirected to the Workbench home page")
def home_page_displayed(page, workbench_url):
    # After login the URL should no longer be the sign-in page.
    assert "sign-in" not in page.url.lower() and "login" not in page.url.lower(), (
        f"Still on the login page: {page.url}"
    )
