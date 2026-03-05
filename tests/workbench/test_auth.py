"""Step definitions for Workbench authentication tests."""

from __future__ import annotations

from playwright.sync_api import Page, expect
from pytest_bdd import given, scenario, then, when

from tests.workbench.conftest import WorkbenchSelectors, workbench_login


@scenario("test_auth.feature", "User can log in to Workbench via the web UI")
def test_workbench_login():
    pass


@given("Workbench is accessible at the configured URL")
def workbench_accessible(workbench_client):
    assert workbench_client is not None, "Workbench client not configured"
    status = workbench_client.health()
    assert status < 400, f"Workbench health-check returned HTTP {status}"


@when("a user navigates to the Workbench login page")
def navigate_to_login(page: Page, workbench_url: str):
    page.goto(workbench_url)
    # Workbench redirects to login automatically; wait for login form
    page.wait_for_selector(WorkbenchSelectors.LOGIN_USERNAME, timeout=15000)


@when("enters valid Workbench credentials")
def enter_credentials(page: Page, workbench_url: str, test_username: str, test_password: str):
    workbench_login(page, workbench_url, test_username, test_password)


@then("the Workbench homepage is displayed")
def homepage_displayed(page: Page):
    expect(page.locator(WorkbenchSelectors.POSIT_LOGO)).to_be_visible(timeout=15000)
    expect(page.locator(WorkbenchSelectors.NEW_SESSION_BUTTON)).to_be_visible(timeout=15000)


@then("the current user is shown in the header")
def current_user_displayed(page: Page, test_username: str):
    current_user = page.locator(WorkbenchSelectors.CURRENT_USER)
    expect(current_user).to_be_visible(timeout=10000)
    expect(current_user).to_have_text(test_username)
