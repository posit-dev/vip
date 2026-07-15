"""Tests for `vip cleanup` command wiring in vip.cli (issue #467).

Exercises run_cleanup()'s Connect/Workbench branching, the Workbench
auth-mode selection (headless vs. interactive), and the API-unreachable /
leftover-sessions escalation to the browser-driven UI sweep. No real network
connections or browsers are used: WorkbenchClient, ConnectClient, and the
auth/UI-sweep functions are monkeypatched.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import vip.auth
import vip.cli
import vip.workbench_ui
from vip.auth import InteractiveAuthSession


def _make_args(**overrides) -> argparse.Namespace:
    defaults = {
        "connect_url": None,
        "api_key": None,
        "workbench_url": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _fake_session(tmp_path: Path) -> InteractiveAuthSession:
    state_path = tmp_path / "vip-auth-state.json"
    state_path.write_text('{"cookies": []}')
    return InteractiveAuthSession(storage_state_path=state_path, _tmpdir="")


class _FakeWorkbenchClient:
    """Stand-in for WorkbenchClient recording calls; instances are reusable."""

    instances: list[_FakeWorkbenchClient] = []

    def __init__(self, base_url, *, cookies=None, insecure=False, ca_bundle=None, **_):
        self.base_url = base_url
        self.cookies = cookies
        self.closed = False
        self._api_reachable = True
        self._quit_count = 0
        self._remaining_sessions: list[dict] = []
        type(self).instances.append(self)

    def sessions_api_reachable(self):
        return self._api_reachable

    def quit_vip_sessions(self):
        return self._quit_count

    def list_sessions(self):
        return self._remaining_sessions

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_workbench_client():
    _FakeWorkbenchClient.instances = []
    yield
    _FakeWorkbenchClient.instances = []


class TestConnectWorkbenchRouting:
    """run_cleanup must run Connect-only, Workbench-only, or both, based on
    which URLs resolve — and error when neither does."""

    def test_neither_url_exits_with_error(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            vip.cli.run_cleanup(_make_args())

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "Connect or Workbench" in err

    def test_connect_only_does_not_touch_workbench(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)

        class _FakeConnectClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def cleanup_vip_content(self):
                return 3

        monkeypatch.setattr("vip.clients.connect.ConnectClient", _FakeConnectClient)

        def _fail(*a, **k):
            pytest.fail("workbench cleanup should not run without a workbench URL")

        monkeypatch.setattr(vip.cli, "_cleanup_workbench_sessions", _fail)

        vip.cli.run_cleanup(_make_args(connect_url="https://c.example.com"))

        out = capsys.readouterr().out
        assert "Deleted 3 VIP test content item(s)" in out
        assert "Cleanup completed successfully" in out

    def test_workbench_only_does_not_touch_connect(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        monkeypatch.delenv("VIP_TEST_USERNAME", raising=False)
        monkeypatch.delenv("VIP_TEST_PASSWORD", raising=False)

        def _fail(*a, **k):
            pytest.fail("Connect client should not be constructed without a Connect URL")

        monkeypatch.setattr("vip.clients.connect.ConnectClient", _fail)

        called = {}
        monkeypatch.setattr(
            vip.cli,
            "_cleanup_workbench_sessions",
            lambda url, args, config: called.setdefault("url", url),
        )

        vip.cli.run_cleanup(_make_args(workbench_url="https://wb.example.com"))

        assert called["url"] == "https://wb.example.com"

    def test_both_urls_clean_both(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)

        class _FakeConnectClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def cleanup_vip_content(self):
                return 1

        monkeypatch.setattr("vip.clients.connect.ConnectClient", _FakeConnectClient)

        called = {}
        monkeypatch.setattr(
            vip.cli,
            "_cleanup_workbench_sessions",
            lambda url, args, config: called.setdefault("url", url),
        )

        vip.cli.run_cleanup(
            _make_args(connect_url="https://c.example.com", workbench_url="https://wb.example.com")
        )

        out = capsys.readouterr().out
        assert "Deleted 1 VIP test content item(s)" in out
        assert called["url"] == "https://wb.example.com"

    def test_workbench_url_falls_back_to_vip_toml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        (tmp_path / "vip.toml").write_text(
            '[workbench]\nurl = "https://wb-from-config.example.com"\n'
        )

        called = {}
        monkeypatch.setattr(
            vip.cli,
            "_cleanup_workbench_sessions",
            lambda url, args, config: called.setdefault("url", url),
        )

        vip.cli.run_cleanup(_make_args())

        assert called["url"] == "https://wb-from-config.example.com"


class TestWorkbenchAuthModeSelection:
    """_cleanup_workbench_sessions must pick headless auth when test creds are
    present, otherwise fall back to interactive."""

    def _patch_client_and_ui(self, monkeypatch, *, api_reachable=True, remaining=None):
        def _fake_client_ctor(*args, **kwargs):
            client = _FakeWorkbenchClient(*args, **kwargs)
            client._api_reachable = api_reachable
            client._remaining_sessions = remaining or []
            return client

        monkeypatch.setattr("vip.clients.workbench.WorkbenchClient", _fake_client_ctor)
        monkeypatch.setattr(vip.workbench_ui, "quit_vip_sessions_via_ui", lambda page, url, **k: 0)

        @contextmanager
        def _fake_authenticated_page(session, **kwargs):
            yield MagicMock()

        monkeypatch.setattr(vip.auth, "authenticated_page", _fake_authenticated_page)

    def test_uses_headless_auth_when_test_credentials_configured(self, tmp_path, monkeypatch):
        from vip.config import VIPConfig

        self._patch_client_and_ui(monkeypatch)

        calls = {}

        def _fake_headless(**kwargs):
            calls["headless"] = kwargs
            return _fake_session(tmp_path)

        monkeypatch.setattr(vip.auth, "start_headless_auth", _fake_headless)

        def _fail_interactive(**kwargs):
            pytest.fail("start_interactive_auth should not be called when creds are configured")

        monkeypatch.setattr(vip.auth, "start_interactive_auth", _fail_interactive)

        config = VIPConfig()
        config.auth.username = "admin"
        config.auth.password = "secret"

        vip.cli._cleanup_workbench_sessions("https://wb.example.com", _make_args(), config)

        assert calls["headless"]["workbench_url"] == "https://wb.example.com"
        assert calls["headless"]["username"] == "admin"

    def test_uses_interactive_auth_when_no_credentials(self, tmp_path, monkeypatch):
        from vip.config import VIPConfig

        self._patch_client_and_ui(monkeypatch)

        def _fail_headless(**kwargs):
            pytest.fail("start_headless_auth should not be called without credentials")

        monkeypatch.setattr(vip.auth, "start_headless_auth", _fail_headless)

        calls = {}

        def _fake_interactive(**kwargs):
            calls["interactive"] = kwargs
            return _fake_session(tmp_path)

        monkeypatch.setattr(vip.auth, "start_interactive_auth", _fake_interactive)

        config = VIPConfig()
        config.auth.username = ""
        config.auth.password = ""

        vip.cli._cleanup_workbench_sessions("https://wb.example.com", _make_args(), config)

        assert calls["interactive"]["workbench_url"] == "https://wb.example.com"

    def test_auth_config_error_exits_with_clear_message(self, tmp_path, monkeypatch, capsys):
        from vip.auth import AuthConfigError
        from vip.config import VIPConfig

        def _boom(**kwargs):
            raise AuthConfigError("no credentials")

        monkeypatch.setattr(vip.auth, "start_interactive_auth", _boom)

        config = VIPConfig()
        config.auth.username = ""
        config.auth.password = ""

        with pytest.raises(SystemExit) as exc_info:
            vip.cli._cleanup_workbench_sessions("https://wb.example.com", _make_args(), config)

        assert exc_info.value.code == 1
        assert "could not authenticate" in capsys.readouterr().err

    def test_unexpected_auth_exception_does_not_crash_with_traceback(
        self, tmp_path, monkeypatch, capsys
    ):
        from vip.config import VIPConfig

        def _boom(**kwargs):
            raise RuntimeError("browser crashed")

        monkeypatch.setattr(vip.auth, "start_interactive_auth", _boom)

        config = VIPConfig()
        config.auth.username = ""
        config.auth.password = ""

        with pytest.raises(SystemExit) as exc_info:
            vip.cli._cleanup_workbench_sessions("https://wb.example.com", _make_args(), config)

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "could not authenticate to Workbench" in err
        assert "VIP_TEST_USERNAME" in err


class TestWorkbenchUiEscalation:
    """The UI sweep must fire when the API is unreachable or leaves VIP
    sessions behind, and must be skipped when the API sweep is confirmed clean."""

    def _run(self, tmp_path, monkeypatch, *, api_reachable, remaining):
        from vip.config import VIPConfig

        monkeypatch.setattr(vip.auth, "start_interactive_auth", lambda **k: _fake_session(tmp_path))

        def _fake_client_ctor(*args, **kwargs):
            client = _FakeWorkbenchClient(*args, **kwargs)
            client._api_reachable = api_reachable
            client._remaining_sessions = remaining
            return client

        monkeypatch.setattr("vip.clients.workbench.WorkbenchClient", _fake_client_ctor)

        ui_calls: list[str] = []
        monkeypatch.setattr(
            vip.workbench_ui,
            "quit_vip_sessions_via_ui",
            lambda page, url, **k: ui_calls.append(url) or 0,
        )

        @contextmanager
        def _fake_authenticated_page(session, **kwargs):
            yield MagicMock()

        monkeypatch.setattr(vip.auth, "authenticated_page", _fake_authenticated_page)

        config = VIPConfig()
        config.auth.username = ""
        config.auth.password = ""

        vip.cli._cleanup_workbench_sessions("https://wb.example.com", _make_args(), config)
        return ui_calls

    def test_escalates_when_api_unreachable(self, tmp_path, monkeypatch):
        ui_calls = self._run(tmp_path, monkeypatch, api_reachable=False, remaining=[])
        assert ui_calls == ["https://wb.example.com"]

    def test_escalates_when_leftovers_remain_despite_reachable_api(self, tmp_path, monkeypatch):
        ui_calls = self._run(
            tmp_path,
            monkeypatch,
            api_reachable=True,
            remaining=[{"id": "a", "label": "VIP stuck"}],
        )
        assert ui_calls == ["https://wb.example.com"]

    def test_skips_ui_when_api_sweep_is_clean(self, tmp_path, monkeypatch):
        ui_calls = self._run(tmp_path, monkeypatch, api_reachable=True, remaining=[])
        assert ui_calls == []
