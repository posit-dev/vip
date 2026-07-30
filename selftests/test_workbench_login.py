"""Selftests for workbench_login's password-vs-SSO detection (issue #467).

On an OIDC-only Workbench (no password form), the config-less password-login
path must *skip* gracefully rather than fall through to the password retry
loop and fail with "Login failed after 3 attempts". The sign-in page renders
client-side, so detection must wait for either the username field or the
"Sign in with OpenID" button before deciding -- a race that previously misread
a slow OIDC sign-in page as a password deployment.

No real browser is used: a tiny Page double models the sign-in page.
"""

from __future__ import annotations

import pytest
from _pytest.outcomes import Skipped
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from vip_tests.workbench.conftest import workbench_login


class _AuthFakeLocator:
    def __init__(self, *, visible: bool = False, on_click=None):
        self._visible = visible
        self._on_click = on_click

    @property
    def first(self):
        return self

    def is_visible(self) -> bool:
        return self._visible()

    def wait_for(self, *, state=None, timeout=None):
        if not self._visible():
            # Playwright's Locator.wait_for raises PlaywrightTimeoutError on timeout;
            # model that so the SSO-skip path exercises the same typed catch as production.
            raise PlaywrightTimeoutError("locator not visible")

    def click(self, *args, **kwargs):
        if self._on_click is not None:
            self._on_click()

    def or_(self, other):
        """Model Playwright's Locator.or_ -- visible when either side is."""
        return _AuthFakeLocator(visible=lambda: self._visible() or other._visible())


class _OidcLoginFakePage:
    """Models an OIDC-only sign-in page: a "Sign in with OpenID" button and no
    username field. *idp_valid* controls whether clicking the button reaches an
    authenticated homepage (the logo becoming visible)."""

    def __init__(self, *, idp_valid: bool = True):
        self.url = "https://wb.example.com/auth-sign-in?appUri=&error=2"
        self._logged_in = False
        self._idp_valid = idp_valid
        self.sso_clicked = False

    def goto(self, *args, **kwargs):
        pass

    def wait_for_load_state(self, *args, **kwargs):
        pass

    def locator(self, selector):
        from vip_tests.workbench.pages import Homepage

        if selector == Homepage.POSIT_LOGO:
            return _AuthFakeLocator(visible=lambda: self._logged_in)
        # Everything else this flow queries (the username field, the combined
        # settle-wait selector) is absent on an OIDC-only page.
        return _AuthFakeLocator(visible=lambda: False)

    def get_by_role(self, role, name=None):
        def _click():
            self.sso_clicked = True
            if self._idp_valid:
                self._logged_in = True

        return _AuthFakeLocator(visible=lambda: True, on_click=_click)


def test_password_login_skips_on_oidc_only_deployment():
    # Config-less defaults: auth_provider="password", interactive_auth=False.
    page = _OidcLoginFakePage()
    with pytest.raises(Skipped) as exc:
        workbench_login(page, "https://wb.example.com", "user", "pass")
    assert "SSO/OIDC" in str(exc.value)
    assert page.sso_clicked is False  # password mode never clicks the SSO button


def test_interactive_auth_completes_sso_and_returns():
    # --interactive-auth with a valid pre-loaded IdP session: click SSO, land on
    # the homepage, and return without skipping.
    page = _OidcLoginFakePage(idp_valid=True)
    workbench_login(page, "https://wb.example.com", "", "", interactive_auth=True)
    assert page.sso_clicked is True


def test_interactive_auth_skips_when_sso_cannot_complete():
    # --interactive-auth but the IdP session is gone: clicking SSO never reaches
    # the homepage, so skip gracefully instead of hanging or failing.
    page = _OidcLoginFakePage(idp_valid=False)
    with pytest.raises(Skipped):
        workbench_login(page, "https://wb.example.com", "", "", interactive_auth=True)
    assert page.sso_clicked is True


class _ExternalIdpFakePage:
    """Models a deployment that redirects sign-in out to a third-party IdP.

    Hitting Workbench unauthenticated lands on the IdP's own page (e.g. Okta's
    ``/oauth2/v1/authorize``), which has neither Workbench's ``#username`` field
    nor a "Sign in with ..." button -- Okta's identifier-first submit is named
    "Next".  The old detection read that as a password deployment and ground the
    retry loop into "Login failed after 3 attempts".
    """

    def __init__(self):
        self.url = (
            "https://posit.okta.com/oauth2/v1/authorize?client_id=abc"
            "&redirect_uri=https%3A%2F%2Fsso.example.com%2F__oauth__&response_type=code"
        )
        self.filled: list[tuple[str, str]] = []

    def goto(self, *args, **kwargs):
        pass

    def wait_for_load_state(self, *args, **kwargs):
        pass

    def locator(self, selector):
        # Nothing Workbench-specific exists on the IdP's page.
        return _AuthFakeLocator(visible=lambda: False)

    def get_by_role(self, role, name=None):
        # No control matching /sign in/i -- Okta's button is named "Next".
        return _AuthFakeLocator(visible=lambda: False)

    def fill(self, selector, value):
        self.filled.append((selector, value))


def test_password_login_skips_when_workbench_federates_to_external_idp():
    page = _ExternalIdpFakePage()
    with pytest.raises(Skipped) as exc:
        workbench_login(page, "https://wb.example.com", "user", "pass")
    message = str(exc.value)
    assert "posit.okta.com" in message, "the skip must name the IdP that took over sign-in"
    assert page.filled == [], "must not attempt a password form on the IdP's page"


def test_interactive_auth_skips_when_redirected_to_external_idp():
    page = _ExternalIdpFakePage()
    with pytest.raises(Skipped) as exc:
        workbench_login(page, "https://wb.example.com", "", "", interactive_auth=True)
    assert "posit.okta.com" in str(exc.value)


class _PasswordLoginFakePage:
    """A real Workbench password deployment: own origin, own ``#username`` field."""

    def __init__(self):
        self.url = "https://wb.example.com/auth-sign-in"
        self._logged_in = False
        self.filled: list[tuple[str, str]] = []

    def goto(self, *args, **kwargs):
        pass

    def wait_for_load_state(self, *args, **kwargs):
        pass

    def locator(self, selector):
        from vip_tests.workbench.pages import Homepage, LoginPage

        if selector == Homepage.POSIT_LOGO:
            return _AuthFakeLocator(visible=lambda: self._logged_in)
        if selector in (LoginPage.USERNAME, f"{LoginPage.USERNAME}, button:has-text('Sign in')"):
            return _AuthFakeLocator(visible=lambda: True)
        return _AuthFakeLocator(visible=lambda: False)

    def get_by_role(self, role, name=None):
        # A password form's submit button also matches /sign in/i.
        return _AuthFakeLocator(visible=lambda: True)

    def fill(self, selector, value):
        self.filled.append((selector, value))

    def click(self, selector):
        self._logged_in = True


def test_password_deployment_still_uses_the_login_form():
    """Guard: the SSO detection must not swallow genuine password deployments."""
    page = _PasswordLoginFakePage()
    workbench_login(page, "https://wb.example.com", "user", "pass")
    assert ("#username", "user") in page.filled
    assert ("#password", "pass") in page.filled
