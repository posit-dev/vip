"""Unit tests for vip.timeouts — VIP_TIMEOUT_SCALE helpers."""

from __future__ import annotations

import importlib

import vip.timeouts as timeouts_mod
from vip.timeouts import scaled, timeout_scale


class TestTimeoutScale:
    def test_default_is_one(self, monkeypatch):
        monkeypatch.delenv("VIP_TIMEOUT_SCALE", raising=False)
        assert timeout_scale() == 1.0

    def test_reads_env_var(self, monkeypatch):
        monkeypatch.setenv("VIP_TIMEOUT_SCALE", "2.5")
        assert timeout_scale() == 2.5

    def test_invalid_string_falls_back(self, monkeypatch):
        monkeypatch.setenv("VIP_TIMEOUT_SCALE", "abc")
        assert timeout_scale() == 1.0

    def test_zero_falls_back(self, monkeypatch):
        monkeypatch.setenv("VIP_TIMEOUT_SCALE", "0")
        assert timeout_scale() == 1.0

    def test_negative_falls_back(self, monkeypatch):
        monkeypatch.setenv("VIP_TIMEOUT_SCALE", "-1")
        assert timeout_scale() == 1.0

    def test_fractional_scale(self, monkeypatch):
        monkeypatch.setenv("VIP_TIMEOUT_SCALE", "0.5")
        assert timeout_scale() == 0.5

    def test_empty_string_falls_back(self, monkeypatch):
        monkeypatch.setenv("VIP_TIMEOUT_SCALE", "")
        assert timeout_scale() == 1.0


class TestScaled:
    def test_default_returns_value_unchanged(self, monkeypatch):
        monkeypatch.delenv("VIP_TIMEOUT_SCALE", raising=False)
        assert scaled(30.0) == 30.0

    def test_scale_two_doubles_value(self, monkeypatch):
        monkeypatch.setenv("VIP_TIMEOUT_SCALE", "2")
        assert scaled(30.0) == 60.0

    def test_scale_half_halves_value(self, monkeypatch):
        monkeypatch.setenv("VIP_TIMEOUT_SCALE", "0.5")
        assert scaled(30.0) == 15.0


class TestWorkbenchConftestConstants:
    """Verify that workbench conftest constants reflect VIP_TIMEOUT_SCALE."""

    def test_constants_scale_on_reload(self, monkeypatch):
        import vip_tests.workbench.conftest as conftest

        monkeypatch.setenv("VIP_TIMEOUT_SCALE", "2")
        importlib.reload(conftest)
        try:
            assert conftest.TIMEOUT_SESSION_START == 180_000
            assert conftest.TIMEOUT_IDE_LOAD == 120_000
            assert conftest.TIMEOUT_PAGE_LOAD == 30_000
            assert conftest.TIMEOUT_QUICK == 10_000
        finally:
            monkeypatch.delenv("VIP_TIMEOUT_SCALE", raising=False)
            importlib.reload(conftest)

    def test_constants_default_at_scale_one(self, monkeypatch):
        import vip_tests.workbench.conftest as conftest

        monkeypatch.delenv("VIP_TIMEOUT_SCALE", raising=False)
        importlib.reload(conftest)
        try:
            assert conftest.TIMEOUT_SESSION_START == 90_000
            assert conftest.TIMEOUT_IDE_LOAD == 60_000
        finally:
            importlib.reload(conftest)


class TestBaseClientTimeout:
    """Verify that BaseClient respects the None-sentinel scaling."""

    def test_no_explicit_timeout_uses_scaled_default(self, monkeypatch):
        monkeypatch.setenv("VIP_TIMEOUT_SCALE", "2")
        # Reload timeouts module so scale is picked up.
        importlib.reload(timeouts_mod)
        from vip.clients.base import BaseClient

        client = BaseClient("http://example.com")
        effective = client._client.timeout.read  # type: ignore[union-attr]
        assert effective == 60.0
        client.close()

    def test_explicit_timeout_opts_out(self, monkeypatch):
        monkeypatch.setenv("VIP_TIMEOUT_SCALE", "3")
        importlib.reload(timeouts_mod)
        from vip.clients.base import BaseClient

        client = BaseClient("http://example.com", timeout=5.0)
        effective = client._client.timeout.read  # type: ignore[union-attr]
        assert effective == 5.0
        client.close()
