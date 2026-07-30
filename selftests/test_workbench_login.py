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


# ---------------------------------------------------------------------------
# Sign-out must not leave the shared session signed out (issue #467 / #263)
# ---------------------------------------------------------------------------


def test_signout_runs_after_every_other_workbench_scenario():
    """Sign-out destroys the session every other Workbench test shares.

    It must therefore be ordered *after* them.  It used to inherit the module's
    ``order(10)`` -- the earliest mark in the whole Workbench suite -- so the
    one test that signs the shared account out ran before nearly everything
    else, while sibling xdist workers were mid-test.
    """
    from vip_tests.workbench import test_auth

    signout_order = [
        m.args[0] for m in test_auth.test_workbench_signout.pytestmark if m.name == "order"
    ]
    assert signout_order, "test_workbench_signout needs its own explicit order mark"

    # Every other Workbench module's order mark must come first.
    other_orders = [10, 20, 30, 40, 45, 50, 60, 90]
    assert signout_order[-1] > max(other_orders), (
        f"sign-out is ordered {signout_order[-1]}, which runs before other Workbench "
        f"scenarios (max {max(other_orders)})"
    )


def test_login_scenario_still_runs_early():
    """The login scenario uses its own logged-out context, so it stays early."""
    from vip_tests.workbench import test_auth

    login_order = [
        m.args[0] for m in test_auth.test_workbench_login.pytestmark if m.name == "order"
    ]
    assert login_order, "test_workbench_login needs its own explicit order mark"
    assert login_order[-1] <= 10


def test_auth_module_does_not_set_a_shared_order_mark():
    """The two scenarios run at opposite ends, so neither may inherit one order.

    A module-level ``pytestmark`` stacked under a per-function mark leaves the
    winner up to pytest-order's resolution; keep both explicit instead.
    """
    from vip_tests.workbench import test_auth

    module_marks = getattr(test_auth, "pytestmark", [])
    marks = module_marks if isinstance(module_marks, list) else [module_marks]
    assert not [m for m in marks if getattr(m, "name", "") == "order"]


def test_restore_shared_session_reports_failure_to_reauthenticate(caplog):
    """When silent SSO cannot get back in, say so loudly rather than silently.

    A failed restore leaves every later scenario -- and the cached auth session
    on disk -- pointing at a signed-out server session, so it must not be
    swallowed.
    """
    import logging

    from vip_tests.workbench.test_auth import _restore_shared_session

    class _DeadPage:
        url = "https://wb.example.com/auth-sign-in"

        def goto(self, *a, **k):
            pass

        def wait_for_load_state(self, *a, **k):
            pass

        def locator(self, selector):
            return _AuthFakeLocator(visible=lambda: False)

        def get_by_role(self, role, name=None):
            return _AuthFakeLocator(visible=lambda: False)

    with caplog.at_level(logging.WARNING):
        assert _restore_shared_session(_DeadPage(), "https://wb.example.com") is False
    assert any("sign" in r.message.lower() for r in caplog.records), caplog.records


def test_restore_shared_session_returns_true_when_homepage_comes_back():
    from vip_tests.workbench.test_auth import _restore_shared_session

    class _RecoveredPage:
        url = "https://wb.example.com/"

        def goto(self, *a, **k):
            pass

        def wait_for_load_state(self, *a, **k):
            pass

        def locator(self, selector):
            from vip_tests.workbench.pages import Homepage

            visible = selector == Homepage.POSIT_LOGO
            return _AuthFakeLocator(visible=lambda: visible)

        def get_by_role(self, role, name=None):
            return _AuthFakeLocator(visible=lambda: True)

    assert _restore_shared_session(_RecoveredPage(), "https://wb.example.com") is True
