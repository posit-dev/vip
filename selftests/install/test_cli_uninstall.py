"""Tests for the `vip uninstall` CLI command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


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


def test_run_uninstall_silent_when_vip_toml_missing(tmp_path, monkeypatch, capsys):
    """No vip.toml present: no warning, just continues without chained cleanup."""
    import argparse
    import socket

    from vip import cli

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
    # Note: NO vip.toml in tmp_path.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VIP_CONFIG", raising=False)

    args = argparse.Namespace(
        yes=True,
        venv=False,
        system=False,
        force_host=False,
        connect_url=None,
        api_key=None,
    )

    with pytest.raises(SystemExit) as exc:
        cli.run_uninstall(args)
    assert exc.value.code == 0

    captured = capsys.readouterr()
    assert "warning: failed to load vip.toml" not in captured.err


def test_run_uninstall_warns_on_malformed_vip_toml(tmp_path, monkeypatch, capsys):
    """Malformed vip.toml during uninstall: emit a warning, continue."""
    import argparse
    import socket

    from vip import cli

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
    # Malformed TOML.
    (tmp_path / "vip.toml").write_text("[connect\nurl = bogus")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VIP_CONFIG", raising=False)

    args = argparse.Namespace(
        yes=True,
        venv=False,
        system=False,
        force_host=False,
        connect_url=None,
        api_key=None,
    )

    with pytest.raises(SystemExit) as exc:
        cli.run_uninstall(args)
    assert exc.value.code == 0

    captured = capsys.readouterr()
    assert "warning: failed to load vip.toml" in captured.err


def test_run_uninstall_chained_cleanup_invokes_connect_client(tmp_path, monkeypatch):
    """When connect_url is set, run_uninstall constructs a callable that opens
    ConnectClient and calls cleanup_vip_content."""
    import argparse
    import socket

    from vip import cli

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

    monkeypatch.chdir(tmp_path)

    invocations = []

    class FakeConnectClient:
        def __init__(self, url, api_key):
            invocations.append(("init", url, api_key))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cleanup_vip_content(self):
            invocations.append(("cleanup",))
            return 0

    # Patch the import inside the cleanup callable.
    import vip.clients.connect as connect_mod

    monkeypatch.setattr(connect_mod, "ConnectClient", FakeConnectClient)

    args = argparse.Namespace(
        yes=True,
        venv=False,
        system=False,
        force_host=False,
        connect_url="https://connect.example.com",
        api_key="fake-api-key",
    )

    with pytest.raises(SystemExit) as exc:
        cli.run_uninstall(args)
    assert exc.value.code == 0
    # Verify the chained cleanup was invoked.
    assert any(call[0] == "cleanup" for call in invocations)
    assert ("init", "https://connect.example.com", "fake-api-key") in invocations
