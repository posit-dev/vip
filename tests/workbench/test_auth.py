"""Step definitions for Workbench authentication tests."""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import given, scenario, then, when

from tests.workbench.conftest import (
    TIMEOUT_DIALOG,
    assert_homepage_loaded,
    workbench_login,
)
from tests.workbench.pages import Homepage


@scenario("test_auth.feature", "User can log in to Workbench via the web UI")
def test_workbench_login():
    pass


@given("Workbench is accessible at the configured URL")
def workbench_accessible(workbench_client, auth_provider: str, interactive_auth: bool):
    # This test only validates password-based login form flow
    if auth_provider != "password":
        pytest.skip(f"test_auth only supports password auth, not {auth_provider!r}")
    if interactive_auth:
        pytest.skip("test_auth is not compatible with --interactive-auth")

    assert workbench_client is not None, "Workbench client not configured"
    status = workbench_client.health()
    assert status < 400, f"Workbench health-check returned HTTP {status}"


@when("a user navigates to the Workbench login page and enters valid credentials")
def navigate_and_login(
    page: Page,
    workbench_url: str,
    test_username: str,
    test_password: str,
):
    """Log in using password auth form."""
    workbench_login(page, workbench_url, test_username, test_password)


@then("the Workbench homepage is displayed")
def homepage_displayed(page: Page):
    assert_homepage_loaded(page)


@then("the current user is shown in the header")
def current_user_displayed(page: Page, test_username: str):
    current_user = page.locator(Homepage.CURRENT_USER)
    expect(current_user).to_be_visible(timeout=TIMEOUT_DIALOG)
    expect(current_user).to_have_text(test_username)
