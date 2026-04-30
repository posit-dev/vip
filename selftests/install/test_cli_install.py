"""Tests for the `vip install` CLI command."""

from __future__ import annotations

import subprocess
from pathlib import Path


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
