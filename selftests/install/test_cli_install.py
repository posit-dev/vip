"""Tests for the `vip install` CLI command."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def test_vip_install_help_lists_command():
    cp = subprocess.run(["uv", "run", "vip", "--help"], capture_output=True, text=True, check=True)
    assert "install" in cp.stdout


def test_vip_install_dry_run_on_macos_or_unsupported(tmp_path: Path, monkeypatch):
    """End-to-end smoke for --dry-run on a platform that won't actually do anything."""
    monkeypatch.chdir(tmp_path)
    cp = subprocess.run(
        ["uv", "run", "vip", "install", "--dry-run"],
        capture_output=True,
        text=True,
    )
    # Either prints a plan or reports up-to-date; never errors.
    assert cp.returncode == 0
    assert "vip install" in cp.stdout


def test_run_install_handles_playwright_install_error(tmp_path, monkeypatch, capsys):
    """A PlaywrightInstallError surfaces as a clean stderr + exit 1."""
    import argparse

    from vip import cli
    from vip.install import runner as rn
    from vip.install.playwright import PlaywrightInstallError

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        rn, "install_chromium", lambda: (_ for _ in ()).throw(PlaywrightInstallError("boom"))
    )
    # Force the plan to require chromium install: pretend cache is empty.
    from vip.install import playwright as pw

    monkeypatch.setattr(pw, "chromium_installed", lambda d: False)

    args = argparse.Namespace(skip_system=True, dry_run=False)
    with pytest.raises(SystemExit) as exc_info:
        cli.run_install(args)
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "boom" in captured.err
    assert "Error" in captured.err
