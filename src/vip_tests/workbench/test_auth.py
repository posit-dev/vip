"""Step definitions for Workbench authentication tests."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Browser, Page, expect
from pytest_bdd import given, scenario, then, when

from vip_tests.workbench.conftest import (
    TIMEOUT_DIALOG,
    TIMEOUT_PAGE_LOAD,
    assert_homepage_loaded,
    workbench_login,
)
from vip_tests.workbench.pages import Homepage, LoginPage


@scenario("test_auth.feature", "User can log in to Workbench via the web UI")
def test_workbench_login():
    pass


@scenario("test_auth.feature", "User can sign out of Workbench")
def test_workbench_signout():
    pass


@pytest.fixture
def page(request: pytest.FixtureRequest, browser: Browser, browser_context_args: dict):
    """Override the default page fixture for the login-form test only.

    The login scenario must genuinely exercise the password login form, so it
    needs a *logged-out* context: storage_state (injected by --interactive-auth
    / --headless-auth) is stripped. Every other test in this module — notably
    the sign-out scenario — must stay *logged in* via that session, so they
    keep storage_state. Stripping it for sign-out would leave the browser
    anonymous and, under SSO, unable to re-authenticate (no password), so the
    "I am logged in" precondition could never be met.

    All other context args (TLS, CA bundle, etc.) are preserved so this page
    behaves consistently with the rest of the suite. The autouse
    _cleanup_sessions fixture in workbench/conftest.py uses this same page,
    keeping cleanup and execution in the same context.
    """
    strip_storage_state = request.node.name.startswith("test_workbench_login")
    args = {
        k: v
        for k, v in browser_context_args.items()
        if not (strip_storage_state and k == "storage_state")
    }
    context = browser.new_context(**args)
    pg = context.new_page()
    try:
        yield pg
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


@then("the current user element is visible and non-empty in the header")
def current_user_displayed(page: Page):
    current_user = page.locator(Homepage.CURRENT_USER)
    expect(current_user).to_be_visible(timeout=TIMEOUT_DIALOG)
    expect(current_user).not_to_be_empty(timeout=TIMEOUT_DIALOG)


# ---------------------------------------------------------------------------
# Sign-out steps
# ---------------------------------------------------------------------------


@when("I sign out of Workbench")
def sign_out(page: Page):
    """Click the sign-out button on the Workbench homepage.

    Tries the legacy ``#signOutBtn`` first; on newer Workbench versions the
    sign-out form is not rendered until the user menu is opened, so click the
    current-user button to reveal it before submitting.
    """
    old_btn = page.locator(Homepage.SIGN_OUT_BTN_OLD)
    if old_btn.is_visible():
        old_btn.click()
    else:
        page.locator(Homepage.CURRENT_USER).click()
        sign_out_form = page.locator(Homepage.SIGN_OUT_FORM)
        expect(sign_out_form).to_be_visible(timeout=TIMEOUT_DIALOG)
        submit = sign_out_form.locator("button, input[type='submit'], a")
        if submit.count() > 0:
            submit.first.click()
        else:
            # The form renders as the menu entry itself with no submit
            # control inside it; submit it directly to fire the sign-out POST.
            sign_out_form.evaluate("form => form.submit()")


@then("I am redirected to the Workbench login page")
def redirected_to_login_page(page: Page):
    """Verify the login page is shown after sign-out.

    Password deployments render the native form (``#username``); SSO/OIDC
    deployments render a "Sign in with <provider>" page that has no username
    field. Accept either affordance, and fall back to the login URL so the
    check is independent of the configured auth provider.
    """
    username = page.locator(LoginPage.USERNAME)
    sign_in_button = page.get_by_role("button", name=re.compile(r"sign in", re.IGNORECASE))
    username_or_signin = username.or_(sign_in_button)
    try:
        username_or_signin.wait_for(state="visible", timeout=TIMEOUT_PAGE_LOAD)
    except Exception:
        expect(page).to_have_url(re.compile(r"sign-in|login|auth"), timeout=TIMEOUT_PAGE_LOAD)
