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


class TestGetCode:
    def test_env_set_returns_generated_code(self, monkeypatch):
        monkeypatch.setenv(ENV_VAR, "JBSWY3DPEHPK3PXP")

        # input() must not be called when env is set.
        monkeypatch.setattr(
            "builtins.input",
            lambda *a, **kw: pytest.fail("input() was called even though env var was set"),
        )

        from vip.totp import get_code

        code = get_code(">>> prompt: ")
        assert code.isdigit()
        assert len(code) == 6

    def test_env_set_matches_pyotp_reference(self, monkeypatch):
        """Code returned must match pyotp.TOTP(seed).now() for the same instant."""
        import pyotp

        seed = "JBSWY3DPEHPK3PXP"
        monkeypatch.setenv(ENV_VAR, seed)

        from vip.totp import get_code

        # Take two readings close together; one of them must match the
        # reference computed in the same window. (A 30-second tick boundary
        # between calls would make a single comparison flaky.)
        ref_before = pyotp.TOTP(seed).now()
        code = get_code()
        ref_after = pyotp.TOTP(seed).now()
        assert code in {ref_before, ref_after}

    def test_env_unset_calls_input(self, monkeypatch):
        monkeypatch.delenv(ENV_VAR, raising=False)

        captured = {}

        def fake_input(prompt=""):
            captured["prompt"] = prompt
            return "  123456  "

        monkeypatch.setattr("builtins.input", fake_input)

        from vip.totp import get_code

        code = get_code(">>> custom prompt: ")
        assert code == "123456"
        assert captured["prompt"] == ">>> custom prompt: "

    def test_env_empty_falls_back_to_input(self, monkeypatch):
        """Whitespace-only env value should not be treated as a seed."""
        monkeypatch.setenv(ENV_VAR, "   ")

        called = {"yes": False}

        def fake_input(prompt=""):
            called["yes"] = True
            return "654321"

        monkeypatch.setattr("builtins.input", fake_input)

        from vip.totp import get_code

        code = get_code()
        assert called["yes"] is True
        assert code == "654321"
