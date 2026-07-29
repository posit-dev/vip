"""Tests for the scheme-inference fallback wiring in vip.cli (issue #537).

``_resolved_url`` and its call sites in ``_collect_status`` (``vip status``),
``run_cleanup`` (``vip cleanup``), and ``run_uninstall``'s chained-cleanup
callable all need the same probe-and-fallback treatment as ``vip verify``:
a scheme-less URL defaults to https:// (``vip.config._normalize_url``) and
falls back to http:// only when https genuinely doesn't answer
(``vip.auth.resolve_url_scheme``), never for a URL the caller gave an
explicit scheme for.
"""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import httpx
import pytest

from vip.config import ConnectConfig


class TestResolvedUrlCli:
    """``vip.cli._resolved_url`` mirrors conftest.py's fixture-level helper."""

    def setup_method(self):
        import vip.auth

        vip.auth._scheme_resolution_cache.clear()

    def test_explicit_scheme_never_probes(self):
        from vip.cli import _resolved_url

        pc = ConnectConfig(url="https://connect.example.com")

        with patch("httpx.get") as mock_get:
            url = _resolved_url(pc)

        assert url == "https://connect.example.com"
        mock_get.assert_not_called()

    def test_inferred_scheme_kept_when_https_answers(self):
        from vip.cli import _resolved_url

        pc = ConnectConfig(url="connect.example.com")
        assert pc.url_scheme_inferred is True

        with patch("httpx.get", return_value=MagicMock(status_code=200)):
            url = _resolved_url(pc)

        assert url == "https://connect.example.com"
        assert pc.url == "https://connect.example.com"

    def test_inferred_scheme_falls_back_and_mutates_in_place(self):
        pc = ConnectConfig(url="connect.example.com")

        from vip.cli import _resolved_url

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")):
            url = _resolved_url(pc)

        assert url == "http://connect.example.com"
        assert pc.url == "http://connect.example.com"

    def test_insecure_and_ca_bundle_forwarded(self, tmp_path):
        from vip.cli import _resolved_url

        ca = tmp_path / "ca.pem"
        pc = ConnectConfig(url="connect.example.com")

        with patch("httpx.get", return_value=MagicMock(status_code=200)) as mock_get:
            _resolved_url(pc, insecure=True, ca_bundle=ca)

        assert mock_get.call_args.kwargs["verify"] is False


class TestCollectStatusSchemeResolution:
    """``vip status`` must not get stuck on a wrong inferred scheme, and must
    not probe a URL the user gave a scheme for."""

    def setup_method(self):
        import vip.auth

        vip.auth._scheme_resolution_cache.clear()

    def _config(self, url: str):
        from vip.config import VIPConfig

        cfg = VIPConfig()
        cfg.connect = ConnectConfig(url=url, enabled=True)
        return cfg

    def test_explicit_scheme_no_probe(self):
        from vip.cli import _collect_status

        config = self._config("https://connect.example.com")
        mock_client = MagicMock()
        mock_client.health.return_value = 200

        with patch("httpx.get") as mock_get:
            with patch("vip.clients.connect.ConnectClient", return_value=mock_client) as ctor:
                result = _collect_status(config)

        mock_get.assert_not_called()
        assert ctor.call_args.args[0] == "https://connect.example.com"
        assert result["products"]["connect"]["state"] == "ok"

    def test_inferred_scheme_falls_back_before_client_construction(self):
        """A bare hostname that only serves plain HTTP must still report a
        real status, not 'fail' from ConnectClient choking on an https://
        URL that doesn't answer."""
        from vip.cli import _collect_status

        config = self._config("connect.example.com")
        mock_client = MagicMock()
        mock_client.health.return_value = 200

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")):
            with patch("vip.clients.connect.ConnectClient", return_value=mock_client) as ctor:
                result = _collect_status(config)

        assert ctor.call_args.args[0] == "http://connect.example.com"
        assert result["products"]["connect"]["url"] == "http://connect.example.com"
        assert result["products"]["connect"]["state"] == "ok"


class TestRunCleanupSchemeResolution:
    """``vip cleanup --connect-url``/``--workbench-url`` route a bare hostname
    through the same normalization + fallback as every other entry point --
    previously a scheme-less CLI flag was handed to ConnectClient completely
    unnormalized (httpx requires an absolute URL) and never got a fallback."""

    def setup_method(self):
        import vip.auth

        vip.auth._scheme_resolution_cache.clear()

    @staticmethod
    def _args(**overrides) -> argparse.Namespace:
        defaults = {"connect_url": None, "api_key": None, "workbench_url": None}
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_bare_hostname_connect_url_is_normalized_and_resolved(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)

        class _FakeConnectClient:
            def __init__(self, *a, **k):
                self.url = a[0]

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def cleanup_vip_content(self):
                return 0

        constructed: list[str] = []
        orig_init = _FakeConnectClient.__init__

        def _record_init(self, *a, **k):
            constructed.append(a[0])
            orig_init(self, *a, **k)

        _FakeConnectClient.__init__ = _record_init
        monkeypatch.setattr("vip.clients.connect.ConnectClient", _FakeConnectClient)

        import vip.cli

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")):
            vip.cli.run_cleanup(self._args(connect_url="connect.example.com"))

        assert constructed == ["http://connect.example.com"]
        assert "http://connect.example.com" in capsys.readouterr().out

    def test_explicit_scheme_connect_url_never_probes(self, tmp_path, monkeypatch):
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
                return 0

        monkeypatch.setattr("vip.clients.connect.ConnectClient", _FakeConnectClient)

        import vip.cli

        with patch("httpx.get") as mock_get:
            vip.cli.run_cleanup(self._args(connect_url="https://c.example.com"))

        mock_get.assert_not_called()


def _write_manifest(tmp_path) -> None:
    """Write a minimal .vip-install.json matching the current host, per the
    established pattern in selftests/install/test_cli_uninstall.py."""
    import json
    import socket

    manifest = {
        "version": 1,
        "vip_version": "0.0.0",
        "created_at": "t",
        "updated_at": "t",
        "host": socket.gethostname(),
        "platform": "rhel-family",
        "platform_id": "rhel",
        "platform_version": "10",
        "items": [],
        "pending_system_packages": [],
    }
    (tmp_path / ".vip-install.json").write_text(json.dumps(manifest))


class TestRunUninstallSchemeResolution:
    """The chained-cleanup callable in ``vip uninstall`` resolves an inferred
    scheme lazily -- only when actually invoked (--yes), never during a
    dry-run plan preview."""

    def setup_method(self):
        import vip.auth

        vip.auth._scheme_resolution_cache.clear()

    def test_dry_run_never_probes(self, tmp_path, monkeypatch):
        """Without --yes, execute_uninstall_plan never calls cleanup_callable
        at all -- confirm no network call happens building up to that point."""
        import vip.cli as cli

        _write_manifest(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)

        args = argparse.Namespace(
            connect_url="connect.example.com", api_key=None, force_host=False, yes=False
        )
        with patch("httpx.get") as mock_get:
            with pytest.raises(SystemExit) as exc:
                cli.run_uninstall(args)

        assert exc.value.code == 0
        mock_get.assert_not_called()

    def test_yes_resolves_inferred_scheme_before_client_construction(self, tmp_path, monkeypatch):
        import vip.cli as cli
        import vip.clients.connect as connect_mod

        _write_manifest(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)

        constructed: list[str] = []

        class _FakeConnectClient:
            def __init__(self, url, *a, **k):
                constructed.append(url)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def cleanup_vip_content(self):
                return 0

        monkeypatch.setattr(connect_mod, "ConnectClient", _FakeConnectClient)

        args = argparse.Namespace(
            connect_url="connect.example.com", api_key=None, force_host=False, yes=True
        )
        with patch("httpx.get", side_effect=httpx.ConnectError("nope")):
            with pytest.raises(SystemExit) as exc:
                cli.run_uninstall(args)

        assert exc.value.code == 0
        assert constructed == ["http://connect.example.com"]

    def test_explicit_scheme_never_probes(self, tmp_path, monkeypatch):
        import vip.cli as cli
        import vip.clients.connect as connect_mod

        _write_manifest(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)

        class _FakeConnectClient:
            def __init__(self, url, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def cleanup_vip_content(self):
                return 0

        monkeypatch.setattr(connect_mod, "ConnectClient", _FakeConnectClient)

        args = argparse.Namespace(
            connect_url="https://connect.example.com", api_key=None, force_host=False, yes=True
        )
        with patch("httpx.get") as mock_get:
            with pytest.raises(SystemExit) as exc:
                cli.run_uninstall(args)

        assert exc.value.code == 0
        mock_get.assert_not_called()
