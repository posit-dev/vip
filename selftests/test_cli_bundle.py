"""Tests for the ``vip bundle`` subcommand (run_bundle in vip.cli)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from pathlib import Path

import pytest

import vip.cli.bundle as bundle_module
from vip.bundle.stamp import record_rendered, results_digest
from vip.cli import main, run_bundle
from vip.errors import BundleError

_VIP_SECRET_ENV = (
    "VIP_CONFIG",
    "VIP_CONNECT_API_KEY",
    "VIP_WORKBENCH_API_KEY",
    "VIP_GIT_TOKEN",
    "VIP_PACKAGE_MANAGER_TOKEN",
    "VIP_PM_TOKEN",
    "VIP_TEST_USERNAME",
    "VIP_TEST_PASSWORD",
    "VIP_TEST_TOTP_SECRET",
)

CONNECT_KEY = "SECRET-connect-api-key"
MINTED_KEY = "MINTED-KEY-0001"
SESSION_COOKIE = "COOKIE-SESSION-0123456789"

VIP_TOML = f"""\
[general]
deployment_name = "Acme Prod"

[connect]
url = "https://connect.example.com"
api_key = "{CONNECT_KEY}"

[workbench]
url = "https://workbench.example.com"
api_key = "SECRET-workbench-api-key"

[workbench.git_test]
clone_url = "https://SECRET-git-user-token@github.com/org/repo.git"
token = "SECRET-git-token"

[package_manager]
url = "https://pm.example.com"
token = "SECRET-pm-token"

[auth]
username = "alice"
password = "SECRET-auth-password"

[data_sources.pg]
type = "postgres"
connection_string = "postgresql://dbuser:SECRET-db-password@db:5432/app"

[proxy]
url = "http://puser:SECRET-proxy-password@proxy:8080"
"""

ALL_SEEDED_SECRETS = (
    CONNECT_KEY,
    "SECRET-workbench-api-key",
    "SECRET-git-user-token",
    "SECRET-git-token",
    "SECRET-pm-token",
    "SECRET-auth-password",
    "SECRET-db-password",
    "SECRET-proxy-password",
    MINTED_KEY,
    SESSION_COOKIE,
)

RESULTS_MTIME = 1_000_000.0


def _args(**overrides) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "results": None,
        "config": None,
        "no_config": False,
        "output": None,
        "force": False,
        "allow_match": [],
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _write(path: Path, text: str, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime, mtime))


def _write_report(
    root: Path, results_extra: str = "", failures_extra: str = "", deployment: str = "Acme Prod"
) -> None:
    """Write report files as vip verify and vip report leave them.

    failures.json is newer than results.json, and the render stamp ties
    index.html to results.json.
    """
    report = root / "report"
    results = {
        "deployment_name": deployment,
        "products": {"connect": {"url": "https://connect.example.com"}},
        "results": [],
        "note": results_extra,
    }
    _write(report / "results.json", json.dumps(results), RESULTS_MTIME)
    failures = {"failures": [{"error_summary": f"HTTP 401 {failures_extra}"}]}
    _write(report / "failures.json", json.dumps(failures), RESULTS_MTIME + 1)
    _write(report / "_output" / "index.html", "<html>report</html>", RESULTS_MTIME + 2)
    digest = results_digest((report / "results.json").read_bytes())
    record_rendered(report / "_output", digest, ("index.html",))
    _write(report / "notes.txt", "not allowlisted", RESULTS_MTIME + 2)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    for var in _VIP_SECRET_ENV:
        monkeypatch.delenv(var, raising=False)
    # A later auth_cache_path() reads XDG_CACHE_HOME. Keep it out of the real home.
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))


@pytest.fixture
def root(tmp_path, monkeypatch) -> Path:
    """An invocation directory as ``vip verify`` and ``vip report`` leave it."""
    (tmp_path / "vip.toml").write_text(VIP_TOML, encoding="utf-8")
    (tmp_path / ".vip-auth-cache.json").write_text(
        json.dumps({"cookies": [{"name": "session", "value": SESSION_COOKIE}]}),
        encoding="utf-8",
    )
    (tmp_path / ".vip-auth-cache.meta.json").write_text(
        json.dumps({"api_key": MINTED_KEY}), encoding="utf-8"
    )
    (tmp_path / ".vip-install.json").write_text("{}", encoding="utf-8")
    _write_report(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _names(zip_path: Path) -> set[str]:
    with zipfile.ZipFile(zip_path) as zf:
        return set(zf.namelist())


def _leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.suffix in {".zip", ".tmp"})


def test_bundle_holds_only_allowlisted_files_and_no_secret(root):
    run_bundle(_args(output="b.zip"))
    with zipfile.ZipFile(root / "b.zip") as zf:
        names = set(zf.namelist())
        data = b"".join(zf.read(n) for n in names)
    assert names == {
        "report/results.json",
        "report/failures.json",
        "report/_output/index.html",
        "config-summary.json",
        "version.txt",
        "manifest.json",
    }
    for secret in ALL_SEEDED_SECRETS:
        assert secret.encode() not in data
    assert b"[connect]" not in data


def test_manifest_lists_members_and_missing_files(root):
    run_bundle(_args(output="b.zip"))
    with zipfile.ZipFile(root / "b.zip") as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["members"] == sorted(_names(root / "b.zip"))
    assert "report/_output/vip-report.pdf" in manifest["missing"]
    assert manifest["left_out"] == []
    assert manifest["allowed_matches"] == []
    assert manifest["config_summary"] is True
    assert manifest["secret_scan"] == "config"


def test_manifest_records_how_many_secrets_the_scan_knew(root, capsys):
    run_bundle(_args(output="b.zip"))
    with zipfile.ZipFile(root / "b.zip") as zf:
        manifest = json.loads(zf.read("manifest.json"))
    # vip.toml holds nine credential values. The cache holds a cookie and a minted key.
    assert manifest["secret_scan_sources"] == {
        "configuration_and_environment": 9,
        "auth_cache": 2,
    }
    out = capsys.readouterr().out
    assert "9 from the configuration and the environment, 2 from the auth cache" in out


def test_scan_with_no_known_secret_warns(root, capsys):
    (root / "vip.toml").unlink()
    (root / ".vip-auth-cache.json").unlink()
    (root / ".vip-auth-cache.meta.json").unlink()
    run_bundle(_args(output="b.zip", no_config=True))
    with zipfile.ZipFile(root / "b.zip") as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["secret_scan_sources"] == {
        "configuration_and_environment": 0,
        "auth_cache": 0,
    }
    assert any("knew no credential" in w for w in manifest["warnings"])
    assert "Warning: the secret scan knew no credential" in capsys.readouterr().err


def test_scan_with_no_auth_cache_does_not_warn_when_the_config_has_secrets(root, capsys):
    (root / ".vip-auth-cache.json").unlink()
    (root / ".vip-auth-cache.meta.json").unlink()
    run_bundle(_args(output="b.zip"))
    assert "knew no credential" not in capsys.readouterr().err


def test_secret_in_failures_json_blocks_bundle(root, capsys):
    _write_report(root, failures_extra=f"key={CONNECT_KEY}")
    with pytest.raises(BundleError) as exc:
        run_bundle(_args(output="b.zip"))
    message = str(exc.value)
    # The error names the file on disk, relative to the working directory.
    assert f"\n  {Path('report') / 'failures.json'}: connect.api_key\n" in message
    assert "Edit each file to remove the value" in message
    assert "--allow-match LABEL" in message
    assert CONNECT_KEY not in message
    captured = capsys.readouterr()
    assert CONNECT_KEY not in captured.out + captured.err
    assert _leftovers(root) == []


def test_secret_in_a_made_member_names_it(root):
    # A weak password that is also a setting that is not secret.
    toml = (root / "vip.toml").read_text(encoding="utf-8")
    (root / "vip.toml").write_text(
        toml.replace('password = "SECRET-auth-password"', 'password = "postgres"'),
        encoding="utf-8",
    )
    with pytest.raises(BundleError) as exc:
        run_bundle(_args(output="b.zip"))
    assert "config-summary.json (made by vip bundle): auth.password" in str(exc.value)
    assert "Change the credential" in str(exc.value)


def test_allow_match_writes_the_bundle_and_records_it(root, capsys):
    toml = (root / "vip.toml").read_text(encoding="utf-8")
    (root / "vip.toml").write_text(
        toml.replace('password = "SECRET-auth-password"', 'password = "postgres"'),
        encoding="utf-8",
    )
    run_bundle(_args(output="b.zip", allow_match=["auth.password"]))
    with zipfile.ZipFile(root / "b.zip") as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["allowed_matches"] == [
        {"member": "config-summary.json", "label": "auth.password"}
    ]
    assert "because --allow-match auth.password is set" in capsys.readouterr().err


def test_allow_match_does_not_cover_other_labels(root):
    _write_report(root, failures_extra=CONNECT_KEY)
    with pytest.raises(BundleError, match=r"connect\.api_key"):
        run_bundle(_args(output="b.zip", allow_match=["auth.password"]))


def test_allow_match_with_an_unknown_label_fails(root):
    with pytest.raises(BundleError, match=r"names no known credential: connect\.apikey"):
        run_bundle(_args(output="b.zip", allow_match=["connect.apikey"]))


def test_manifest_is_scanned_too(root, monkeypatch):
    # Only the manifest holds the value: the path of --results is in a warning there.
    run_dir = root / "Run-Dir-0123"
    _write(run_dir / "results.json", '{"deployment_name": "Acme Prod", "results": []}', 5.0)
    monkeypatch.setenv("VIP_TEST_TOTP_SECRET", "Run-Dir-0123")
    with pytest.raises(BundleError, match=r"manifest\.json \(made by vip bundle\)"):
        run_bundle(_args(output="b.zip", results=str(run_dir / "results.json")))


def test_minted_key_in_root_cache_blocks_bundle(root, tmp_path, monkeypatch):
    # auth_cache_path() points elsewhere, so only the file in the root holds the key.
    other = tmp_path / "other-cache" / ".vip-auth-cache.json"
    monkeypatch.setattr(bundle_module, "auth_cache_path", lambda: other)
    _write_report(root, results_extra=MINTED_KEY)
    with pytest.raises(BundleError, match="auth cache api_key"):
        run_bundle(_args(output="b.zip"))


def test_root_cache_is_read_before_auth_cache_path(root, monkeypatch):
    # The cache files in the root must be read before auth_cache_path() runs,
    # because an auth_cache_path() with a side effect can remove them.
    def migrating_auth_cache_path():
        (root / ".vip-auth-cache.meta.json").unlink()
        return root / "moved" / ".vip-auth-cache.json"

    monkeypatch.setattr(bundle_module, "auth_cache_path", migrating_auth_cache_path)
    _write_report(root, results_extra=MINTED_KEY)
    with pytest.raises(BundleError, match="auth cache api_key"):
        run_bundle(_args(output="b.zip"))


def test_results_path_sets_the_root(root, tmp_path, monkeypatch):
    # Run from another directory: vip.toml and the auth cache come from the
    # directory that holds report/.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    _write_report(root, results_extra=MINTED_KEY)
    with pytest.raises(BundleError, match="auth cache api_key"):
        run_bundle(_args(output="b.zip", results=str(root / "report" / "results.json")))


def test_config_for_another_deployment_fails(root):
    _write_report(root, deployment="Acme Staging")
    with pytest.raises(BundleError, match=r"does not match results\.json"):
        run_bundle(_args(output="b.zip"))


def test_config_with_another_product_url_fails(root):
    toml = (root / "vip.toml").read_text(encoding="utf-8")
    (root / "vip.toml").write_text(
        toml.replace("https://connect.example.com", "https://connect.staging.example.com"),
        encoding="utf-8",
    )
    with pytest.raises(BundleError, match="the connect URL is"):
        run_bundle(_args(output="b.zip"))


def test_key_in_auth_cache_path_blocks_bundle(root, tmp_path, monkeypatch):
    # The auth cache can live outside the invocation directory. The bundle
    # must read the file at auth_cache_path() too, not only the file in the root.
    user_cache = tmp_path / "user-cache" / ".vip-auth-cache.json"
    user_cache.parent.mkdir()
    user_cache.with_suffix(".meta.json").write_text(
        json.dumps({"api_key": "USER-CACHE-KEY-01"}), encoding="utf-8"
    )
    monkeypatch.setattr(bundle_module, "auth_cache_path", lambda: user_cache)
    _write_report(root, results_extra="USER-CACHE-KEY-01")
    with pytest.raises(BundleError, match="auth cache api_key"):
        run_bundle(_args(output="b.zip"))


def test_results_path_sets_the_rendered_files_dir(root, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    run_bundle(_args(output="b.zip", results=str(root / "report" / "results.json")))
    assert "report/_output/index.html" in _names(elsewhere / "b.zip")


def test_runs_from_inside_report_dir(root, monkeypatch):
    monkeypatch.chdir(root / "report")
    run_bundle(_args())
    (zip_path,) = root.glob("vip-bundle-*.zip")
    assert "report/results.json" in _names(zip_path)
    assert "config-summary.json" in _names(zip_path)
    assert not list((root / "report").glob("*.zip"))


def test_inside_report_dir_still_scans_config_and_cache(root, monkeypatch):
    _write_report(root, results_extra=MINTED_KEY, failures_extra=CONNECT_KEY)
    monkeypatch.chdir(root / "report")
    with pytest.raises(BundleError) as exc:
        run_bundle(_args())
    assert "connect.api_key" in str(exc.value)
    assert "auth cache api_key" in str(exc.value)


def test_missing_config_fails_without_flag(root):
    (root / "vip.toml").unlink()
    with pytest.raises(BundleError, match="--no-config"):
        run_bundle(_args(output="b.zip"))
    assert _leftovers(root) == []


def test_explicit_missing_config_fails(root):
    with pytest.raises(BundleError, match=r"no configuration file found at other\.toml"):
        run_bundle(_args(output="b.zip", config="other.toml"))


def test_bad_config_fails_cleanly(root):
    (root / "vip.toml").write_text("[connect\n", encoding="utf-8")
    with pytest.raises(BundleError, match="could not read"):
        run_bundle(_args(output="b.zip"))


def test_no_config_flag_bundles_and_warns(root, capsys):
    (root / "vip.toml").unlink()
    run_bundle(_args(output="b.zip", no_config=True))
    with zipfile.ZipFile(root / "b.zip") as zf:
        manifest = json.loads(zf.read("manifest.json"))
        names = set(zf.namelist())
    assert manifest["config_summary"] is False
    assert manifest["secret_scan"] == "no-config"
    assert "config-summary.json" not in names
    assert "Warning: --no-config is set" in capsys.readouterr().err


def test_no_config_scan_still_uses_env_key(root, monkeypatch):
    (root / "vip.toml").unlink()
    monkeypatch.setenv("VIP_CONNECT_API_KEY", "ENV-KEY-1234")
    _write_report(root, results_extra="ENV-KEY-1234")
    with pytest.raises(BundleError, match=r"connect\.api_key"):
        run_bundle(_args(output="b.zip", no_config=True))


def test_stale_render_is_left_out_and_warns(root, capsys):
    # vip verify ran again, but vip report did not.
    results = root / "report" / "results.json"
    text = results.read_text(encoding="utf-8").replace('"results": []', '"results": [{"n": 1}]')
    results.write_text(text, encoding="utf-8")
    os.utime(root / "report" / "failures.json")
    run_bundle(_args(output="b.zip"))
    assert "report/_output/index.html" not in _names(root / "b.zip")
    err = capsys.readouterr().err
    assert "was not made from" in err
    assert "Run 'vip report' again" in err


def test_short_secret_warns(root, capsys):
    toml = (root / "vip.toml").read_text(encoding="utf-8")
    (root / "vip.toml").write_text(
        toml.replace('password = "SECRET-auth-password"', 'password = "abc"'),
        encoding="utf-8",
    )
    run_bundle(_args(output="b.zip"))
    assert "the value of auth.password is shorter than 4 characters" in capsys.readouterr().err


def test_existing_output_needs_force(root):
    (root / "b.zip").write_bytes(b"old")
    with pytest.raises(BundleError, match="--force"):
        run_bundle(_args(output="b.zip"))
    run_bundle(_args(output="b.zip", force=True))
    assert "manifest.json" in _names(root / "b.zip")


def test_default_output_name(root, capsys):
    run_bundle(_args())
    (zip_path,) = root.glob("vip-bundle-*.zip")
    assert re.fullmatch(r"vip-bundle-acme-prod-\d{8}T\d{6}Z\.zip", zip_path.name)
    assert "Bundle written:" in capsys.readouterr().out


def test_unwritable_output_dir_fails_cleanly(root):
    with pytest.raises(BundleError, match="could not write"):
        run_bundle(_args(output="no-such-dir/b.zip"))


def test_bundle_subcommand_is_registered(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["vip", "bundle", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--output" in out
    assert "--no-config" in out
    assert "--allow-match" in out


def test_bundle_error_exits_with_code_one(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["vip", "bundle", "--no-config"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "Error: no results found" in capsys.readouterr().err
