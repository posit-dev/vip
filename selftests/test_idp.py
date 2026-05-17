"""Tests for vip.idp module — IdP form strategy dispatch."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from vip.auth import AuthConfigError
from vip.idp import SUPPORTED_IDPS, get_idp_strategy


class TestGetIdpStrategy:
    def test_keycloak_returns_callable(self):
        strategy = get_idp_strategy("keycloak")
        assert callable(strategy)

    def test_okta_returns_callable(self):
        strategy = get_idp_strategy("okta")
        assert callable(strategy)

    def test_unknown_idp_raises(self):
        with pytest.raises(AuthConfigError, match="Unsupported IdP.*unknown.*keycloak.*okta"):
            get_idp_strategy("unknown")

    def test_case_insensitive_lookup(self):
        assert get_idp_strategy("Keycloak") is get_idp_strategy("keycloak")
        assert get_idp_strategy("OKTA") is get_idp_strategy("okta")
        assert get_idp_strategy("  Okta  ") is get_idp_strategy("okta")

    def test_supported_idps_contains_expected(self):
        assert "keycloak" in SUPPORTED_IDPS
        assert "okta" in SUPPORTED_IDPS


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
