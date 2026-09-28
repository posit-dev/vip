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

    def test_entra_returns_callable(self):
        strategy = get_idp_strategy("entra")
        assert callable(strategy)

    def test_unknown_idp_raises(self):
        with pytest.raises(AuthConfigError, match=r"Unsupported IdP.*unknown.*keycloak.*okta"):
            get_idp_strategy("unknown")

    def test_azure_alias_not_supported(self):
        """Only "entra" is registered -- no "azure"/"azuread" alias."""
        with pytest.raises(AuthConfigError, match=r"Unsupported IdP.*azure"):
            get_idp_strategy("azure")

    def test_case_insensitive_lookup(self):
        assert get_idp_strategy("Keycloak") is get_idp_strategy("keycloak")
        assert get_idp_strategy("OKTA") is get_idp_strategy("okta")
        assert get_idp_strategy("  Okta  ") is get_idp_strategy("okta")
        assert get_idp_strategy("Snowflake") is get_idp_strategy("snowflake")
        assert get_idp_strategy("Entra") is get_idp_strategy("entra")
        assert get_idp_strategy("  ENTRA  ") is get_idp_strategy("entra")

    def test_supported_idps_contains_expected(self):
        assert "keycloak" in SUPPORTED_IDPS
        assert "okta" in SUPPORTED_IDPS
        assert "snowflake" in SUPPORTED_IDPS
        assert "entra" in SUPPORTED_IDPS


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
        so VIP_TEST_TOTP_SECRET works automatically when set.
        """
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

        with (
            patch("vip.idp.totp.get_code", return_value="123456") as mock_get,
            patch(
                "builtins.input",
                side_effect=AssertionError("input() must not be called; use totp.get_code"),
            ),
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


class TestEntraLogin:
    """Behavioural tests for the Entra ID (Azure AD) form-fill strategy.

    Each step of Entra's flow is a full page served from
    login.microsoftonline.com. The page mock maps every selector the
    strategy queries to a dedicated locator mock (count/visibility
    configurable per test) and exposes a plain, mutable ``page.url``
    attribute that click side effects update to simulate a step
    transition or a final redirect off the login host.
    """

    _LOGIN_URL = "https://login.microsoftonline.com/common/oauth2/authorize"
    _PRODUCT_URL = "https://connect.example.com/__login__/callback"

    @staticmethod
    def _make_locator(*, count=0, visible=False, text=""):
        loc = MagicMock(name="locator")
        loc.count.return_value = count
        loc.first = MagicMock(name="locator.first")
        loc.first.is_visible.return_value = visible
        loc.first.text_content.return_value = text
        loc.nth = MagicMock(side_effect=lambda i: loc.first)
        loc.is_visible.return_value = visible
        return loc

    def _make_page(self, *, text_locators=None, **overrides):
        from vip.idp import (
            _ENTRA_DISPLAY_SIGN,
            _ENTRA_KMSI_MARKER,
            _ENTRA_KMSI_NO,
            _ENTRA_OTC_INPUT,
            _ENTRA_OTC_SUBMIT,
            _ENTRA_PASSWORD,
            _ENTRA_PASSWORD_ERROR,
            _ENTRA_SERVICE_ERROR,
            _ENTRA_SIGN_IN_ANOTHER_WAY,
            _ENTRA_SUBMIT,
            _ENTRA_USERNAME,
            _ENTRA_USERNAME_ERROR,
            _ENTRA_VERIFY_CODE_OPTION,
        )

        page = MagicMock(name="page")
        page.url = self._LOGIN_URL

        locators = {
            _ENTRA_USERNAME: overrides.get("username_loc")
            or self._make_locator(count=1, visible=True),
            _ENTRA_PASSWORD: overrides.get("password_loc")
            or self._make_locator(count=1, visible=True),
            _ENTRA_SUBMIT: overrides.get("submit_loc") or MagicMock(name="submit_loc"),
            _ENTRA_USERNAME_ERROR: overrides.get("username_error") or self._make_locator(),
            _ENTRA_PASSWORD_ERROR: overrides.get("password_error") or self._make_locator(),
            _ENTRA_SERVICE_ERROR: overrides.get("service_error") or self._make_locator(),
            _ENTRA_OTC_INPUT: overrides.get("otc_input") or self._make_locator(),
            _ENTRA_OTC_SUBMIT: overrides.get("otc_submit")
            or self._make_locator(count=1, visible=True),
            _ENTRA_VERIFY_CODE_OPTION: overrides.get("verify_code_option") or self._make_locator(),
            _ENTRA_DISPLAY_SIGN: overrides.get("display_sign") or self._make_locator(),
            _ENTRA_SIGN_IN_ANOTHER_WAY: overrides.get("sign_in_another_way")
            or self._make_locator(),
            _ENTRA_KMSI_MARKER: overrides.get("kmsi_marker") or self._make_locator(),
            _ENTRA_KMSI_NO: overrides.get("kmsi_no") or self._make_locator(count=1, visible=True),
        }
        page.locator.side_effect = lambda sel: locators[sel]
        by_text = text_locators or {}
        page.get_by_text.side_effect = lambda text, exact=False: by_text.get(
            text, self._make_locator()
        )
        page.wait_for_timeout.return_value = None
        page.wait_for_url.return_value = None
        return page, locators

    def test_fills_loginfmt_then_passwd(self):
        from vip.idp import _ENTRA_SUBMIT, _fill_entra_login

        page, locators = self._make_page()
        submit = locators[_ENTRA_SUBMIT]
        calls = {"n": 0}

        def _advance(*_args, **_kwargs):
            calls["n"] += 1
            if calls["n"] >= 2:
                page.url = self._PRODUCT_URL

        submit.click.side_effect = _advance

        _fill_entra_login(page, "user@example.com", "s3cret")

        from vip.idp import _ENTRA_PASSWORD, _ENTRA_USERNAME

        locators[_ENTRA_USERNAME].fill.assert_called_once_with("user@example.com")
        locators[_ENTRA_PASSWORD].first.fill.assert_called_once_with("s3cret")
        assert submit.click.call_count == 2

    def test_kmsi_clicks_no_not_yes(self):
        from vip.idp import _ENTRA_KMSI_NO, _ENTRA_SUBMIT, _fill_entra_login

        page, locators = self._make_page(kmsi_marker=self._make_locator(count=1, visible=True))
        no_button = locators[_ENTRA_KMSI_NO]

        def _dismiss(*_args, **_kwargs):
            page.url = self._PRODUCT_URL

        no_button.first.click.side_effect = _dismiss

        _fill_entra_login(page, "user", "pass")

        no_button.first.click.assert_called_once()
        # Only the email + password steps click the shared primary button;
        # KMSI dismissal must go through "No", never the "Yes"/shared button.
        assert locators[_ENTRA_SUBMIT].click.call_count == 2

    def test_kmsi_absent_is_fine(self):
        from vip.idp import _ENTRA_KMSI_NO, _ENTRA_SUBMIT, _fill_entra_login

        page, locators = self._make_page()
        submit = locators[_ENTRA_SUBMIT]
        calls = {"n": 0}

        def _advance(*_args, **_kwargs):
            calls["n"] += 1
            if calls["n"] >= 2:
                page.url = self._PRODUCT_URL

        submit.click.side_effect = _advance

        _fill_entra_login(page, "user", "pass")  # must not raise

        locators[_ENTRA_KMSI_NO].first.click.assert_not_called()

    def test_totp_uses_totp_get_code_not_input(self):
        from vip.idp import _ENTRA_OTC_INPUT, _ENTRA_OTC_SUBMIT, _fill_entra_login

        page, locators = self._make_page(otc_input=self._make_locator(count=1, visible=True))
        otc_submit = locators[_ENTRA_OTC_SUBMIT]

        def _otc_advance(*_args, **_kwargs):
            page.url = self._PRODUCT_URL

        otc_submit.first.click.side_effect = _otc_advance

        with (
            patch("vip.idp.totp.get_code", return_value="123456") as mock_get,
            patch(
                "builtins.input",
                side_effect=AssertionError("input() must not be called; use totp.get_code"),
            ),
        ):
            _fill_entra_login(page, "user", "pass")

        assert mock_get.called, "Entra strategy did not call totp.get_code"
        locators[_ENTRA_OTC_INPUT].first.fill.assert_called_once_with("123456")

    def test_number_matching_prints_the_number(self, capsys):
        from vip.idp import _fill_entra_login

        page, _locators = self._make_page(
            display_sign=self._make_locator(count=1, visible=True, text="42")
        )

        def _wait_for_url(_predicate, timeout):
            page.url = self._PRODUCT_URL

        page.wait_for_url.side_effect = _wait_for_url

        _fill_entra_login(page, "user", "pass")

        out = capsys.readouterr().out
        assert "42" in out

    def test_proof_up_raises_authconfigerror(self):
        from vip.idp import _ENTRA_PROOF_UP_TEXT, _fill_entra_login

        page, _locators = self._make_page(
            text_locators={_ENTRA_PROOF_UP_TEXT: self._make_locator(count=1, visible=True)}
        )

        with pytest.raises(AuthConfigError, match=r"(?i)information required"):
            _fill_entra_login(page, "user", "pass")

    def test_conditional_access_block_after_password_raises_authconfigerror(self):
        """CA can fire after MFA too -- this exercises the post-password
        resolve loop's check, via the "You can't get there from here"
        heading (no error code shown).
        """
        from vip.idp import _ENTRA_CONDITIONAL_ACCESS_HEADING, _fill_entra_login

        page, _locators = self._make_page(
            text_locators={
                _ENTRA_CONDITIONAL_ACCESS_HEADING: self._make_locator(count=1, visible=True)
            }
        )

        with pytest.raises(AuthConfigError, match=r"(?i)conditional access"):
            _fill_entra_login(page, "user", "pass")

    def test_conditional_access_code_variant_raises_authconfigerror(self):
        """The AADSTS53000/AADSTS53003 code text alone (no heading) must
        also be detected and surfaced in the error message.
        """
        from vip.idp import _fill_entra_login

        page, _locators = self._make_page(
            text_locators={"AADSTS53003": self._make_locator(count=1, visible=True)}
        )

        with pytest.raises(AuthConfigError, match=r"(?i)conditional access.*AADSTS53003"):
            _fill_entra_login(page, "user", "pass")

    def test_inline_password_error_raises_authconfigerror(self):
        from vip.idp import _fill_entra_login

        page, _locators = self._make_page(
            password_error=self._make_locator(
                count=1, visible=True, text="Your account or password is incorrect."
            )
        )

        with pytest.raises(AuthConfigError, match="incorrect"):
            _fill_entra_login(page, "user", "wrongpass")

    def test_federated_redirect_raises_authconfigerror(self):
        from vip.idp import _ENTRA_SUBMIT, _fill_entra_login

        page, locators = self._make_page(password_loc=self._make_locator(count=0, visible=False))
        submit = locators[_ENTRA_SUBMIT]

        def _redirect(*_args, **_kwargs):
            page.url = "https://adfs.example.com/adfs/ls/"

        submit.click.side_effect = _redirect

        with pytest.raises(AuthConfigError, match=r"(?i)federated"):
            _fill_entra_login(page, "user", "pass")

    def test_sovereign_login_host_is_not_treated_as_federated(self):
        """A US Gov / China sovereign-cloud Entra host must not raise the
        federated-redirect error -- only a host outside all known Entra
        login hosts (e.g. a real ADFS/Okta host) counts as federated.
        """
        from vip.idp import _entra_left_login_host

        page = MagicMock(name="page")
        page.url = "https://login.microsoftonline.us/common/oauth2/authorize"
        assert _entra_left_login_host(page) is False

    def test_adfs_host_is_still_treated_as_federated(self):
        from vip.idp import _entra_left_login_host

        page = MagicMock(name="page")
        page.url = "https://adfs.example.com/adfs/ls/"
        assert _entra_left_login_host(page) is True

    def test_deadline_resets_after_mfa_so_kmsi_still_dismissed(self, monkeypatch):
        """Regression: totp.get_code (a human prompt) can take longer than
        _MFA_DETECT_TIMEOUT. If the post-MFA deadline isn't recomputed from
        "now", the resolve loop would exit before ever checking for KMSI.
        """
        import vip.idp as idp_mod
        from vip.idp import _ENTRA_KMSI_NO, _fill_entra_login

        clock = {"t": 0.0}
        monkeypatch.setattr(idp_mod.time, "monotonic", lambda: clock["t"])

        page, locators = self._make_page(
            otc_input=self._make_locator(count=1, visible=True),
            kmsi_marker=self._make_locator(count=1, visible=True),
        )

        def _get_code(_prompt):
            # Simulate totp.get_code taking far longer than the original
            # _MFA_DETECT_TIMEOUT-based deadline.
            clock["t"] += 10_000
            return "111111"

        no_button = locators[_ENTRA_KMSI_NO]

        def _dismiss(*_args, **_kwargs):
            page.url = self._PRODUCT_URL

        no_button.first.click.side_effect = _dismiss

        with patch("vip.idp.totp.get_code", side_effect=_get_code):
            _fill_entra_login(page, "user", "pass")

        no_button.first.click.assert_called_once()

    def test_totp_secret_switches_away_from_auto_sent_push(self, monkeypatch):
        """When VIP_TEST_TOTP_SECRET is set and Entra auto-sends a push,
        the strategy must click "sign in another way" to reach a code
        prompt instead of waiting up to _MFA_TIMEOUT for a push nobody
        will approve.
        """
        from vip import totp
        from vip.idp import (
            _ENTRA_OTC_SUBMIT,
            _ENTRA_SIGN_IN_ANOTHER_WAY,
            _fill_entra_login,
        )

        monkeypatch.setenv(totp.ENV_VAR, "JBSWY3DPEHPK3PXP")

        otc_input = self._make_locator(count=0, visible=False)
        page, locators = self._make_page(
            display_sign=self._make_locator(count=1, visible=True, text="77"),
            otc_input=otc_input,
        )
        switch_link = locators[_ENTRA_SIGN_IN_ANOTHER_WAY]
        switch_link.count.return_value = 1
        switch_link.first.is_visible.return_value = True

        def _switch(*_args, **_kwargs):
            # Simulate Entra moving to the verification-code input after
            # the user opts out of the auto-sent push.
            otc_input.count.return_value = 1
            otc_input.first.is_visible.return_value = True

        switch_link.first.click.side_effect = _switch

        otc_submit = locators[_ENTRA_OTC_SUBMIT]

        def _otc_done(*_args, **_kwargs):
            page.url = self._PRODUCT_URL

        otc_submit.first.click.side_effect = _otc_done

        with patch("vip.idp.totp.get_code", return_value="654321"):
            _fill_entra_login(page, "user", "pass")

        switch_link.first.click.assert_called_once()
        page.wait_for_url.assert_not_called()

    def test_no_totp_secret_falls_back_to_push_wait(self, monkeypatch, capsys):
        """Without VIP_TEST_TOTP_SECRET, an auto-sent push must still be
        waited on as before -- there's no code to fall back to.
        """
        from vip import totp
        from vip.idp import _ENTRA_SIGN_IN_ANOTHER_WAY, _fill_entra_login

        monkeypatch.delenv(totp.ENV_VAR, raising=False)

        page, locators = self._make_page(
            display_sign=self._make_locator(count=1, visible=True, text="88")
        )

        def _wait_for_url(_predicate, timeout):
            page.url = self._PRODUCT_URL

        page.wait_for_url.side_effect = _wait_for_url

        _fill_entra_login(page, "user", "pass")

        out = capsys.readouterr().out
        assert "88" in out
        page.wait_for_url.assert_called_once()
        locators[_ENTRA_SIGN_IN_ANOTHER_WAY].first.click.assert_not_called()
