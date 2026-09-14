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
        force_host=False,
        connect_url=None,
        api_key=None,
    )

    with pytest.raises(SystemExit) as exc:
        cli.run_uninstall(args)
    assert exc.value.code == 0

    captured = capsys.readouterr()
    assert "warning: failed to load vip.toml" in captured.err


def test_install_then_uninstall_round_trip(tmp_path, monkeypatch):
    """Full cycle: vip install (skip-system, no chromium step needed) writes manifest;
    vip uninstall --yes reads it and removes everything."""
    import argparse

    from vip import cli
    from vip.install import platform as plat
    from vip.install import playwright as pw

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(plat, "detect", lambda: plat.PlatformInfo(family="macos"))
    # Pretend chromium is already cached so playwright step is a no-op.
    monkeypatch.setattr(pw, "chromium_installed", lambda d: True)

    # Install
    install_args = argparse.Namespace(skip_system=True, dry_run=False)
    with pytest.raises(SystemExit) as exc_info:
        cli.run_install(install_args)
    assert exc_info.value.code == 0
    manifest_path = tmp_path / ".vip-install.json"
    assert manifest_path.exists()

    # Uninstall
    uninstall_args = argparse.Namespace(
        yes=True,
        force_host=False,
        connect_url=None,
        api_key=None,
    )
    with pytest.raises(SystemExit) as exc_info:
        cli.run_uninstall(uninstall_args)
    assert exc_info.value.code == 0
    assert not manifest_path.exists()


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
        def __init__(self, url, api_key, insecure=False, ca_bundle=None, proxy=None):
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


def _parse_uninstall(monkeypatch, *argv: str):
    """Parse a `vip uninstall` command line and return the namespace.

    Mirrors test_cli_verify.py's ``_parse_verify``: the parser lives inside
    ``main()``, so reach it by stubbing ``run_uninstall`` and capturing the
    namespace ``main()`` would have dispatched -- no manifest file needed.
    """
    import sys

    from vip import cli

    seen = []
    monkeypatch.setattr(cli, "run_uninstall", seen.append)
    monkeypatch.setattr(sys, "argv", ["vip", "uninstall", *argv])
    cli.main()
    assert seen, "run_uninstall was never reached"
    return seen[0]


def test_insecure_flag_parses(monkeypatch):
    args = _parse_uninstall(monkeypatch, "--insecure")
    assert args.insecure is True


def test_ca_bundle_flag_parses_as_path(monkeypatch, tmp_path):
    bundle = tmp_path / "ca.pem"
    bundle.write_text("fake-pem")
    args = _parse_uninstall(monkeypatch, "--ca-bundle", str(bundle))
    assert args.ca_bundle == bundle
    assert isinstance(args.ca_bundle, Path)


def _uninstall_with_manifest(tmp_path, monkeypatch, **arg_overrides):
    """Write a minimal manifest and run `vip uninstall --yes` against it,
    returning the kwargs the chained-cleanup ConnectClient was constructed
    with (issue #563's --insecure/--ca-bundle must reach that client, not
    just the scheme-resolution probe)."""
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
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VIP_CONFIG", raising=False)

    calls = {}

    class FakeConnectClient:
        def __init__(self, url, api_key, insecure=False, ca_bundle=None, proxy=None):
            calls["insecure"] = insecure
            calls["ca_bundle"] = ca_bundle

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cleanup_vip_content(self):
            return 0

    import vip.clients.connect as connect_mod

    monkeypatch.setattr(connect_mod, "ConnectClient", FakeConnectClient)

    defaults = {
        "yes": True,
        "force_host": False,
        "connect_url": "https://connect.example.com",
        "api_key": None,
        "insecure": False,
        "ca_bundle": None,
    }
    defaults.update(arg_overrides)
    args = argparse.Namespace(**defaults)

    with pytest.raises(SystemExit) as exc:
        cli.run_uninstall(args)
    assert exc.value.code == 0
    return calls


def test_insecure_flag_reaches_connect_client_with_no_vip_toml(tmp_path, monkeypatch):
    # No vip.toml is written here -- the case issue #563 calls out as having
    # nowhere else to put the setting -- so the flag must work standalone.
    assert not (tmp_path / "vip.toml").exists()
    calls = _uninstall_with_manifest(tmp_path, monkeypatch, insecure=True)
    assert calls["insecure"] is True


def test_ca_bundle_flag_reaches_connect_client(tmp_path, monkeypatch):
    bundle = tmp_path / "ca.pem"
    bundle.write_text("fake-pem")
    calls = _uninstall_with_manifest(tmp_path, monkeypatch, ca_bundle=bundle)
    assert calls["ca_bundle"] == bundle


def test_toml_insecure_reaches_connect_client_with_connect_url_flag(tmp_path, monkeypatch):
    """Review round 2 on #563: --connect-url plus a vip.toml carrying
    [tls] insecure = true, with NO --insecure flag, must still reach the
    chained-cleanup ConnectClient. Before this fix, cfg was only loaded when
    --connect-url was omitted, so a --connect-url invocation had no route to
    vip.toml's [tls] settings at all -- this is the combination that was
    actually broken."""
    (tmp_path / "vip.toml").write_text("[tls]\ninsecure = true\n")
    calls = _uninstall_with_manifest(tmp_path, monkeypatch)
    assert calls["insecure"] is True


def test_insecure_and_ca_bundle_together_warns_and_insecure_wins(tmp_path, monkeypatch, recwarn):
    bundle = tmp_path / "ca.pem"
    bundle.write_text("fake-pem")
    calls = _uninstall_with_manifest(tmp_path, monkeypatch, insecure=True, ca_bundle=bundle)
    assert calls["insecure"] is True
    assert calls["ca_bundle"] is None
    messages = [str(w.message) for w in recwarn.list]
    assert any("--insecure" in m and "--ca-bundle" in m for m in messages), messages


def test_toml_only_conflict_warns_and_insecure_wins(tmp_path, monkeypatch, recwarn):
    """[tls] insecure=true + ca_bundle in vip.toml, with NO CLI flags at all
    (and no --connect-url, so run_uninstall loads vip.toml for the URL too),
    must warn and resolve to insecure winning -- same as the CLI-flag
    collision above. Pins a deliberate divergence from `verify`: verify's own
    --config/./vip.toml path never calls _resolve_effective_ca_bundle (it
    loads [tls] straight through vip.config.load_config()), so an identical
    vip.toml warns here but would not warn for `vip verify --config vip.toml`.
    """
    bundle = tmp_path / "ca.pem"
    bundle.write_text("fake-pem")
    (tmp_path / "vip.toml").write_text(
        f'[connect]\nurl = "https://connect.example.com"\n\n'
        f'[tls]\ninsecure = true\nca_bundle = "{bundle}"\n'
    )
    calls = _uninstall_with_manifest(tmp_path, monkeypatch, connect_url=None)
    assert calls["insecure"] is True
    assert calls["ca_bundle"] is None
    messages = [str(w.message) for w in recwarn.list]
    assert any("--insecure" in m and "--ca-bundle" in m for m in messages), messages
