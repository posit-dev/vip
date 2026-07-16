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
            raise RuntimeError("locator not visible")

    def click(self, *args, **kwargs):
        if self._on_click is not None:
            self._on_click()


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
