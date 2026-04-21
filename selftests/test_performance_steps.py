"""Selftests for performance test step skip-path behavior.

Covers:
- test_login_load_times: pre-connect errors are converted to pytest.skip
- test_user_simulation: simulate_pm skips when PM token is missing
"""

from __future__ import annotations

import httpx
import pytest

from vip.config import PackageManagerConfig, PerformanceConfig, VIPConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**pm_kwargs) -> VIPConfig:
    """Return a VIPConfig with PackageManagerConfig built from kwargs."""
    return VIPConfig(package_manager=PackageManagerConfig(**pm_kwargs))


# ---------------------------------------------------------------------------
# test_login_load_times: pre-connect skip path
# ---------------------------------------------------------------------------


class TestLoginLoadTimeSkips:
    """measure_load_time should skip (not fail) on pre-connect transport errors."""

    def _run_measure(self, monkeypatch, exc, product="Connect"):
        """Invoke measure_load_time with httpx.get patched to raise *exc*."""
        import vip_tests.performance.test_login_load_times as mod

        monkeypatch.setattr(
            "vip_tests.performance.test_login_load_times.httpx.get",
            lambda *_a, **_kw: (_ for _ in ()).throw(exc),
        )
        pc = PerformanceConfig()
        cfg = VIPConfig()
        # product_config("connect") returns cfg.connect which has url="" by
        # default, so set it to something non-empty so is_configured is True.
        cfg.connect.url = "http://connect.example.com"
        cfg.connect.enabled = True

        with pytest.raises(pytest.skip.Exception) as exc_info:
            mod.measure_load_time(product, cfg, pc)
        return exc_info.value.msg

    def test_proxy_error_skips(self, monkeypatch):
        msg = self._run_measure(monkeypatch, httpx.ProxyError("proxy refused"))
        assert "not reachable from test runner" in msg
        assert "proxy refused" in msg

    def test_connect_timeout_skips(self, monkeypatch):
        msg = self._run_measure(monkeypatch, httpx.ConnectTimeout("timed out", request=None))
        assert "not reachable from test runner" in msg

    def test_connect_error_skips(self, monkeypatch):
        msg = self._run_measure(monkeypatch, httpx.ConnectError("connection refused"))
        assert "not reachable from test runner" in msg

    def test_skip_message_contains_url(self, monkeypatch):
        msg = self._run_measure(monkeypatch, httpx.ProxyError("proxy refused"))
        assert "http://connect.example.com" in msg

    def test_skip_message_mentions_network_path(self, monkeypatch):
        msg = self._run_measure(monkeypatch, httpx.ProxyError("proxy refused"))
        assert "network path" in msg.lower() or "proxy" in msg.lower()


# ---------------------------------------------------------------------------
# test_user_simulation: simulate_pm token guard
# ---------------------------------------------------------------------------


class TestSimulatePmTokenGuard:
    """simulate_pm should skip when package_manager.token is falsy."""

    # Use a user count that is in the default load_user_counts list so the
    # _check_user_count guard does not fire before the token/URL guard.
    _VALID_USERS = 10

    def _run_simulate_pm(self, monkeypatch, token: str, url: str = "http://pm.example.com"):
        """Call simulate_pm with a config built from *token* and *url*."""
        import vip_tests.performance.test_user_simulation as mod

        cfg = _make_config(url=url, token=token)
        pc = PerformanceConfig()

        with pytest.raises(pytest.skip.Exception) as exc_info:
            mod.simulate_pm(
                users=self._VALID_USERS,
                vip_config=cfg,
                performance_config=pc,
                vip_verbose=False,
            )
        return exc_info.value.msg

    def test_empty_token_skips(self, monkeypatch):
        msg = self._run_simulate_pm(monkeypatch, token="")
        assert "token" in msg.lower()

    def test_skip_message_mentions_package_manager(self, monkeypatch):
        msg = self._run_simulate_pm(monkeypatch, token="")
        assert "package manager" in msg.lower()

    def test_no_url_skips_before_token_check(self, monkeypatch):
        """If the URL is also missing, it should still skip (on URL check)."""
        import vip_tests.performance.test_user_simulation as mod

        cfg = _make_config(url="", token="")
        pc = PerformanceConfig()

        with pytest.raises(pytest.skip.Exception) as exc_info:
            mod.simulate_pm(
                users=self._VALID_USERS,
                vip_config=cfg,
                performance_config=pc,
                vip_verbose=False,
            )
        # Either the URL check or the token check fires — both are skips.
        assert exc_info.value.msg  # just confirm it's a non-empty skip message
