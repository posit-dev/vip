"""Tests for vip.totp — TOTP seed handling for headless MFA."""

from __future__ import annotations

import pytest

from vip.auth import AuthConfigError
from vip.totp import ENV_VAR, validate_secret


class TestValidateSecret:
    def test_valid_base32_passes(self):
        # Canonical pyotp example seed, valid base32.
        validate_secret("JBSWY3DPEHPK3PXP")

    def test_invalid_base32_raises_auth_config_error(self):
        with pytest.raises(AuthConfigError, match=ENV_VAR):
            validate_secret("not-valid-base32-!!!")

    def test_empty_string_raises(self):
        with pytest.raises(AuthConfigError, match=ENV_VAR):
            validate_secret("")
