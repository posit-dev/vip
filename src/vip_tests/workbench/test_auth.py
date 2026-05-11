"""Step definitions for Workbench authentication tests."""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, Page, expect
from pytest_bdd import given, scenario, then, when

from vip.config import VIPConfig
from vip_tests.workbench.conftest import (
    TIMEOUT_DIALOG,
    assert_homepage_loaded,
    workbench_login,
)
from vip_tests.workbench.pages import Homepage


@scenario("test_auth.feature", "User can log in to Workbench via the web UI")
def test_workbench_login():
    pass


@pytest.fixture
def fresh_page(browser: Browser, vip_config: VIPConfig):
    """A browser page with no pre-loaded storage state.

    Exercises the login form even when --headless-auth pre-authenticated
    other tests via storage_state in browser_context_args.
    """
    context_args = {}
    if vip_config.insecure:
        context_args["ignore_https_errors"] = True
    # NODE_EXTRA_CA_CERTS is set globally by browser_context_args in
    # src/vip_tests/conftest.py for ca_bundle, so it applies here too.
    context = browser.new_context(**context_args)
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()


@given("Workbench is accessible at the configured URL")
def workbench_accessible(workbench_client, auth_provider: str):
    # This test only validates password-based login form flow
    if auth_provider != "password":
        pytest.skip(f"test_auth only supports password auth, not {auth_provider!r}")

    assert workbench_client is not None, "Workbench client not configured"
    status = workbench_client.health()
    assert status < 400, f"Workbench health-check returned HTTP {status}"


@when("a user navigates to the Workbench login page and enters valid credentials")
def navigate_and_login(
    fresh_page: Page,
    workbench_url: str,
    test_username: str,
    test_password: str,
):
    """Log in using password auth form."""
    workbench_login(fresh_page, workbench_url, test_username, test_password)


@then("the Workbench homepage is displayed")
def homepage_displayed(fresh_page: Page):
    assert_homepage_loaded(fresh_page)


@then("the current user is shown in the header")
def current_user_displayed(fresh_page: Page, test_username: str):
    current_user = fresh_page.locator(Homepage.CURRENT_USER)
    expect(current_user).to_be_visible(timeout=TIMEOUT_DIALOG)
    expect(current_user).to_have_text(test_username)
