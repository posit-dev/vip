"""Tests for _run_verify_local command assembly in vip.cli."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest


def _make_args(**overrides) -> argparse.Namespace:
    """Build a minimal args namespace for _run_verify_local."""
    defaults = {
        "config": None,
        "connect_url": None,
        "workbench_url": None,
        "package_manager_url": None,
        "report": "report/results.json",
        "interactive_auth": False,
        "extensions": [],
        "categories": None,
        "filter_expr": None,
        "pytest_args": [],
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _capture_cmd(args: argparse.Namespace) -> list[str]:
    """Run _run_verify_local with mocked subprocess and return the command."""
    captured: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        captured.append(list(cmd))
        result = MagicMock()
        result.returncode = 0
        return result

    with (
        patch("vip.cli.subprocess.run", side_effect=fake_run),
        patch("vip.cli.sys.exit"),
    ):
        from vip.cli import _run_verify_local

        _run_verify_local(args)

    assert captured, "subprocess.run was never called"
    return captured[0]


def _vip_tests_path() -> str:
    """Return the resolved vip_tests package path for assertions."""
    from importlib.util import find_spec

    spec = find_spec("vip_tests")
    assert spec and spec.submodule_search_locations
    return spec.submodule_search_locations[0]


class TestVerifyLocalTestPath:
    """The CLI must pass the vip_tests package path to pytest so tests are
    found even when running outside the source tree (pip install)."""

    def test_vip_tests_path_included_by_default(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg)))
        assert _vip_tests_path() in cmd

    def test_vip_tests_path_skipped_when_user_passes_test_file(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), pytest_args=["tests/foo.py"]))
        assert _vip_tests_path() not in cmd

    def test_vip_tests_path_skipped_when_user_passes_nodeid(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), pytest_args=["tests/foo.py::test_bar"]))
        assert _vip_tests_path() not in cmd

    def test_vip_tests_path_kept_with_flag_only_pytest_args(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), pytest_args=["-x", "--tb=short"]))
        assert _vip_tests_path() in cmd

    def test_vip_tests_path_skipped_when_user_passes_directory_target(self, tmp_path):
        """A positional directory argument is a test target."""
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        target_dir = tmp_path / "my_tests"
        target_dir.mkdir()
        cmd = _capture_cmd(_make_args(config=str(cfg), pytest_args=[str(target_dir)]))
        assert _vip_tests_path() not in cmd

    def test_vip_tests_path_kept_when_dir_is_rootdir_value(self, tmp_path):
        """--rootdir value must not trigger false-positive target detection."""
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), pytest_args=["--rootdir", str(tmp_path)]))
        assert _vip_tests_path() in cmd

    def test_vip_tests_path_kept_when_dir_is_confcutdir_value(self, tmp_path):
        """--confcutdir value must not trigger false-positive target detection."""
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), pytest_args=["--confcutdir", str(tmp_path)]))
        assert _vip_tests_path() in cmd


class TestVerifyLocalSkipNotes:
    """Unconfigured products should produce a note before tests run."""

    def test_disabled_product_says_disabled(self, tmp_path, capsys):
        cfg = tmp_path / "vip.toml"
        cfg.write_text(
            "[general]\n"
            "[connect]\nenabled = false\n"
            "[workbench]\nenabled = false\n"
            '[package_manager]\nurl = "http://localhost:4242/"\n'
        )
        _capture_cmd(_make_args(config=str(cfg)))
        out = capsys.readouterr().out
        assert "Connect disabled" in out
        assert "Workbench disabled" in out
        assert "Package Manager" not in out

    def test_missing_url_says_no_url(self, tmp_path, capsys):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        _capture_cmd(_make_args(config=str(cfg)))
        out = capsys.readouterr().out
        assert "Connect no URL given" in out
        assert "Workbench no URL given" in out
        assert "Package Manager no URL given" in out

    def test_no_notes_when_all_products_configured(self, tmp_path, capsys):
        cfg = tmp_path / "vip.toml"
        cfg.write_text(
            "[general]\n"
            '[connect]\nurl = "https://c.example.com"\n'
            '[workbench]\nurl = "https://w.example.com"\n'
            '[package_manager]\nurl = "https://pm.example.com"\n'
        )
        _capture_cmd(_make_args(config=str(cfg)))
        out = capsys.readouterr().out
        assert "will be skipped" not in out

    def test_notes_from_url_args(self, tmp_path, monkeypatch, capsys):
        """URL-argument flow generates a temp config; notes should reflect it."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        _capture_cmd(_make_args(package_manager_url="http://localhost:4242/"))
        out = capsys.readouterr().out
        assert "Connect" in out
        assert "Workbench" in out
        assert "Package Manager" not in out


class TestVerifyLocalVerbose:
    """Review #87: verify -v is included by default in local runs."""

    def test_verbose_flag_present_by_default(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg)))
        assert "-v" in cmd

    def test_user_pytest_args_appended_after_verbose(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), pytest_args=["-x", "--tb=short"]))
        assert "-v" in cmd
        assert "-x" in cmd
        assert "--tb=short" in cmd


class TestVerifyLocalMissingConfig:
    """Review #88: verify exits immediately when config file is missing."""

    def test_explicit_config_missing_exits(self, tmp_path):
        missing = str(tmp_path / "does_not_exist.toml")
        with pytest.raises(SystemExit) as exc_info:
            from vip.cli import _run_verify_local

            _run_verify_local(_make_args(config=missing))
        assert exc_info.value.code == 1

    def test_no_config_no_urls_missing_default_exits(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            from vip.cli import _run_verify_local

            _run_verify_local(_make_args())
        assert exc_info.value.code == 1

    def test_url_args_bypass_missing_default(self, tmp_path, monkeypatch):
        """When URL args are provided, a temp config is generated — no default needed."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        cmd = _capture_cmd(_make_args(connect_url="https://connect.example.com"))
        assert any("--vip-config" in arg for arg in cmd)
