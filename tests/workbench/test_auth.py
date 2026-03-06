"""Step definitions for Workbench authentication tests."""

from __future__ import annotations

from playwright.sync_api import Page, expect
from pytest_bdd import given, scenario, then, when

from tests.workbench.conftest import workbench_login
from tests.workbench.pages import Homepage


@scenario("test_auth.feature", "User can log in to Workbench via the web UI")
def test_workbench_login():
    pass


@given("Workbench is accessible at the configured URL")
def workbench_accessible(workbench_client):
    assert workbench_client is not None, "Workbench client not configured"
    status = workbench_client.health()
    assert status < 400, f"Workbench health-check returned HTTP {status}"


@when("a user navigates to the Workbench login page and enters valid credentials")
def navigate_and_login(page: Page, workbench_url: str, test_username: str, test_password: str):
    """Use the shared workbench_login helper for consistency with other tests."""
    workbench_login(page, workbench_url, test_username, test_password)


@then("the Workbench homepage is displayed")
def homepage_displayed(page: Page):
    expect(page.locator(Homepage.POSIT_LOGO)).to_be_visible(timeout=15000)
    expect(page.locator(Homepage.NEW_SESSION_BUTTON)).to_be_visible(timeout=15000)


@then("the current user is shown in the header")
def current_user_displayed(page: Page, test_username: str):
    current_user = page.locator(Homepage.CURRENT_USER)
    expect(current_user).to_be_visible(timeout=10000)
    expect(current_user).to_have_text(test_username)
