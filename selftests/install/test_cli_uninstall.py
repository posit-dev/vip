"""Tests for the `vip uninstall` CLI command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_vip_uninstall_help_lists_command():
    cp = subprocess.run(["uv", "run", "vip", "--help"], capture_output=True, text=True, check=True)
    assert "uninstall" in cp.stdout


def test_vip_uninstall_no_manifest(tmp_path: Path):
    cp = subprocess.run(
        ["uv", "run", "vip", "uninstall"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert cp.returncode != 0
    assert "No .vip-install.json" in cp.stdout + cp.stderr


def test_vip_uninstall_dry_run_prints_plan(tmp_path: Path):
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
        "items": [
            {
                "kind": "playwright_browser",
                "browser": "chromium",
                "cache_dir": str(tmp_path / "fake-cache"),
                "installed_at": "t",
            }
        ],
        "pending_system_packages": [],
    }
    (tmp_path / ".vip-install.json").write_text(json.dumps(manifest))

    cp = subprocess.run(
        ["uv", "run", "vip", "uninstall"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert cp.returncode == 0
    assert "Dry run" in cp.stdout
    assert "fake-cache" in cp.stdout
    # No --yes — manifest still exists.
    assert (tmp_path / ".vip-install.json").exists()


def test_vip_uninstall_yes_removes_manifest(tmp_path: Path):
    import socket

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    manifest = {
        "version": 1,
        "vip_version": "0.0.0",
        "created_at": "t",
        "updated_at": "t",
        "host": socket.gethostname(),
        "platform": "rhel-family",
        "platform_id": "rhel",
        "platform_version": "10",
        "items": [
            {
                "kind": "playwright_browser",
                "browser": "chromium",
                "cache_dir": str(cache_dir),
                "installed_at": "t",
            }
        ],
        "pending_system_packages": [],
    }
    (tmp_path / ".vip-install.json").write_text(json.dumps(manifest))

    cp = subprocess.run(
        ["uv", "run", "vip", "uninstall", "--yes"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert not (tmp_path / ".vip-install.json").exists()
    assert not cache_dir.exists()


def test_vip_uninstall_host_mismatch_refuses(tmp_path: Path):
    manifest = {
        "version": 1,
        "vip_version": "0.0.0",
        "created_at": "t",
        "updated_at": "t",
        "host": "some-other-host.invalid",
        "platform": "rhel-family",
        "platform_id": "rhel",
        "platform_version": "10",
        "items": [],
        "pending_system_packages": [],
    }
    (tmp_path / ".vip-install.json").write_text(json.dumps(manifest))

    cp = subprocess.run(
        ["uv", "run", "vip", "uninstall"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert cp.returncode != 0
    assert "host" in (cp.stdout + cp.stderr).lower()
