"""Tests for vip.idp module — IdP form strategy dispatch."""

from __future__ import annotations

import pytest

from vip.idp import SUPPORTED_IDPS, get_idp_strategy


class TestGetIdpStrategy:
    def test_keycloak_returns_callable(self):
        strategy = get_idp_strategy("keycloak")
        assert callable(strategy)

    def test_okta_returns_callable(self):
        strategy = get_idp_strategy("okta")
        assert callable(strategy)

    def test_unknown_idp_raises(self):
        with pytest.raises(ValueError, match="Unsupported IdP.*unknown.*keycloak.*okta"):
            get_idp_strategy("unknown")

    def test_supported_idps_contains_expected(self):
        assert "keycloak" in SUPPORTED_IDPS
        assert "okta" in SUPPORTED_IDPS
