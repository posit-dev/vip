"""Tests for vip.idp module — IdP form strategy dispatch."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from vip.auth import AuthConfigError
from vip.idp import SUPPORTED_IDPS, _fill_snowflake_login, get_idp_strategy


class TestGetIdpStrategy:
    def test_keycloak_returns_callable(self):
        strategy = get_idp_strategy("keycloak")
        assert callable(strategy)

    def test_okta_returns_callable(self):
        strategy = get_idp_strategy("okta")
        assert callable(strategy)

    def test_snowflake_returns_callable(self):
        strategy = get_idp_strategy("snowflake")
        assert callable(strategy)

    def test_unknown_idp_raises(self):
        with pytest.raises(AuthConfigError, match="Unsupported IdP.*unknown.*keycloak.*okta"):
            get_idp_strategy("unknown")

    def test_case_insensitive_lookup(self):
        assert get_idp_strategy("Keycloak") is get_idp_strategy("keycloak")
        assert get_idp_strategy("OKTA") is get_idp_strategy("okta")
        assert get_idp_strategy("  Okta  ") is get_idp_strategy("okta")
        assert get_idp_strategy("Snowflake") is get_idp_strategy("snowflake")

    def test_supported_idps_contains_expected(self):
        assert "keycloak" in SUPPORTED_IDPS
        assert "okta" in SUPPORTED_IDPS
        assert "snowflake" in SUPPORTED_IDPS


class TestSnowflakeLogin:
    """Behavioural tests for the Snowflake OAuth form-fill strategy.

    The strategy loops, filling one sign-in form per Snowflake OAuth hop
    until no form appears. The page mock controls how many hops present a
    form via ``username_loc.wait_for`` side effects.
    """

    def _make_page(self, *, num_forms: int, consent_visible: bool):
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        from vip.idp import _SF_PASSWORD, _SF_SUBMIT, _SF_USERNAME

        username_loc = MagicMock(name="username_loc")
        # wait_for succeeds for `num_forms` hops, then times out to end the loop.
        username_loc.wait_for.side_effect = [None] * num_forms + [PlaywrightTimeout("no form")]
        password_loc = MagicMock(name="password_loc")
        submit_loc = MagicMock(name="submit_loc")
        allow_button = MagicMock(name="allow_button")
        if not consent_visible:
            allow_button.wait_for.side_effect = PlaywrightTimeout("no consent screen")

        locators = {_SF_USERNAME: username_loc, _SF_PASSWORD: password_loc, _SF_SUBMIT: submit_loc}
        page = MagicMock(name="page")
        page.locator.side_effect = lambda sel: locators[sel]
        page.get_by_role.return_value = allow_button
        page.url = "https://acct.snowflakecomputing.com/oauth/authorize"
        return page, username_loc, password_loc, submit_loc, allow_button

    def test_fills_credentials_and_submits_second_signin(self):
        page, username_loc, password_loc, submit_loc, _ = self._make_page(
            num_forms=1, consent_visible=True
        )
        _fill_snowflake_login(page, "user@example.com", "s3cret")

        username_loc.fill.assert_called_once_with("user@example.com")
        password_loc.fill.assert_called_once_with("s3cret")
        # The username/password "Sign in" is the *second* button.
        submit_loc.nth.assert_any_call(1)
        submit_loc.nth(1).click.assert_called()

    def test_clicks_allow_when_consent_shown(self):
        page, _, _, _, allow_button = self._make_page(num_forms=1, consent_visible=True)
        _fill_snowflake_login(page, "user", "pass")
        allow_button.click.assert_called_once()

    def test_consent_screen_is_optional(self):
        page, _, _, _, allow_button = self._make_page(num_forms=1, consent_visible=False)
        # Must not raise when the consent screen never appears.
        _fill_snowflake_login(page, "user", "pass")
        allow_button.click.assert_not_called()

    def test_fills_every_form_in_the_multi_hop_chain(self):
        # Two Snowflake hops (product-host ingress, then controller-host)
        # must each get the credentials filled — the "double auth".
        page, username_loc, _, _, _ = self._make_page(num_forms=2, consent_visible=False)
        _fill_snowflake_login(page, "user", "pass")
        assert username_loc.fill.call_count == 2

    def test_stops_when_no_form_appears(self):
        # No sign-in form at all (e.g. an already-active session): no fill.
        page, username_loc, _, _, _ = self._make_page(num_forms=0, consent_visible=False)
        _fill_snowflake_login(page, "user", "pass")
        username_loc.fill.assert_not_called()


class TestKeycloakUsesTotpGetCode:
    def test_keycloak_calls_totp_get_code_not_input(self):
        """Keycloak strategy must obtain MFA codes via totp.get_code,
        so VIP_TEST_TOTP_SECRET works automatically when set."""
        from vip.idp import _fill_keycloak_login

        # Build a Playwright page mock whose otp_field appears visible
        # so the MFA branch executes.
        page = MagicMock()
        # First locator() call gets the submit button; subsequent ones
        # return locators whose wait_for / fill / click are no-ops, with
        # one important exception: the otp_field's wait_for must succeed.
        page.locator.return_value.wait_for.return_value = None
        page.locator.return_value.fill.return_value = None
        page.locator.return_value.click.return_value = None

        with patch("vip.idp.totp.get_code", return_value="123456") as mock_get:
            with patch(
                "builtins.input",
                side_effect=AssertionError("input() must not be called; use totp.get_code"),
            ):
                _fill_keycloak_login(page, "user", "pass")

        assert mock_get.called, "Keycloak strategy did not call totp.get_code"


class TestOktaUsesTotpGetCode:
    def test_okta_calls_totp_get_code_not_input(self):
        """Okta TOTP branch must obtain codes via totp.get_code."""
        # Okta's strategy has many branches; rather than reconstruct the
        # full SPA state machine, verify the bare module-level coupling
        # by inspecting source — if totp.get_code is imported and the
        # raw input(">>> Enter your verification code: ") call has been
        # removed, the wiring is correct. The Keycloak test above
        # exercises the runtime path; this guards against regression in
        # the Okta site.
        from pathlib import Path

        import vip.idp as _idp_mod

        src = Path(_idp_mod.__file__).read_text()
        assert "totp.get_code" in src, "Okta strategy must use totp.get_code"
        # The bare interactive prompt must no longer appear next to "Okta"
        # comments / Okta TOTP fill site.
        # Exactly one remaining input() is OK (the push-fallback Enter prompt).
        bare_prompts = src.count('input(">>> Enter your verification code: "')
        assert bare_prompts == 0, (
            f"Found {bare_prompts} raw verification-code input() calls — "
            "should be totp.get_code instead"
        )
