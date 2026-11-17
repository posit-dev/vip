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
from vip.config import VIPConfig
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
        "results_product_urls": 0,
        "auth_cache": 2,
    }
    out = capsys.readouterr().out
    assert (
        "9 from the configuration and the environment, 0 from the product URLs in "
        "results.json, 2 from the auth cache"
    ) in out


def test_scan_with_no_known_secret_warns(root, capsys):
    (root / "vip.toml").unlink()
    (root / ".vip-auth-cache.json").unlink()
    (root / ".vip-auth-cache.meta.json").unlink()
    run_bundle(_args(output="b.zip", no_config=True))
    with zipfile.ZipFile(root / "b.zip") as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["secret_scan_sources"] == {
        "configuration_and_environment": 0,
        "results_product_urls": 0,
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


@pytest.mark.parametrize(
    "member",
    [
        "junit.xml",
        "results.sarif",
        "_output/index.html",
        "_output/details.html",
        "_output/vip-report.pdf",
    ],
)
def test_secret_in_each_report_file_blocks_bundle(root, member):
    report = root / "report"
    rendered = ("index.html", "details.html", "vip-report.pdf")
    for name in rendered:
        _write(report / "_output" / name, "a clean file", RESULTS_MTIME + 5)
    _write(report / member, "x SECRET-pm-token y", RESULTS_MTIME + 5)
    digest = results_digest((report / "results.json").read_bytes())
    record_rendered(report / "_output", digest, rendered)
    with pytest.raises(BundleError, match=r"package_manager\.token") as exc:
        run_bundle(_args(output="b.zip"))
    assert Path(member).name in str(exc.value)
    assert not (root / "b.zip").exists()


def test_session_cookie_in_root_cache_blocks_bundle(root):
    _write_report(root, results_extra=SESSION_COOKIE)
    with pytest.raises(BundleError, match="auth cache cookie session"):
        run_bundle(_args(output="b.zip"))


def test_session_cookie_in_auth_cache_path_blocks_bundle(root, tmp_path, monkeypatch):
    user_cache = tmp_path / "user-cache" / ".vip-auth-cache.json"
    user_cache.parent.mkdir()
    user_cache.write_text(
        json.dumps({"cookies": [{"name": "sid", "value": "USER-CACHE-COOKIE-0123"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(bundle_module, "auth_cache_path", lambda: user_cache)
    _write_report(root, results_extra="USER-CACHE-COOKIE-0123")
    with pytest.raises(BundleError, match="auth cache cookie sid"):
        run_bundle(_args(output="b.zip"))


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
    assert _leftovers(root) == []


def _refuse_with_a_secret_hit(root, monkeypatch):
    _write_report(root, results_extra=CONNECT_KEY)


def _refuse_with_a_manifest_hit(root, monkeypatch):
    run_dir = root / "Run-Dir-0123"
    _write(run_dir / "results.json", '{"deployment_name": "Acme Prod", "results": []}', 5.0)
    monkeypatch.setenv("VIP_TEST_TOTP_SECRET", "Run-Dir-0123")
    return {"results": str(run_dir / "results.json")}


def _refuse_with_an_unknown_label(root, monkeypatch):
    return {"allow_match": ["connect.apikey"]}


def _refuse_with_a_bad_auth_cache(root, monkeypatch):
    (root / ".vip-auth-cache.json").write_text('{"cookies": [', encoding="utf-8")


def _refuse_with_a_config_mismatch(root, monkeypatch):
    _write_report(root, deployment="Other")


@pytest.mark.parametrize(
    "refuse",
    [
        _refuse_with_a_secret_hit,
        _refuse_with_a_manifest_hit,
        _refuse_with_an_unknown_label,
        _refuse_with_a_bad_auth_cache,
        _refuse_with_a_config_mismatch,
    ],
)
def test_each_refusal_leaves_no_zip_and_no_temp_file(root, monkeypatch, refuse):
    overrides = refuse(root, monkeypatch) or {}
    with pytest.raises(BundleError):
        run_bundle(_args(output="b.zip", **overrides))
    assert _leftovers(root) == []
    assert _leftovers(root / "report") == []


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


def test_config_with_another_scheme_and_path_passes(root):
    # A browser login can change the scheme and the path of the URL that the
    # run records. The host is the same, so the file is the correct one.
    toml = (root / "vip.toml").read_text(encoding="utf-8")
    (root / "vip.toml").write_text(
        toml.replace("https://connect.example.com", "http://connect.example.com/connect/"),
        encoding="utf-8",
    )
    _write_report(root)
    run_bundle(_args(output="b.zip"))
    assert (root / "b.zip").is_file()


def test_config_with_another_port_fails(root):
    toml = (root / "vip.toml").read_text(encoding="utf-8")
    (root / "vip.toml").write_text(
        toml.replace("https://connect.example.com", "https://connect.example.com:8443"),
        encoding="utf-8",
    )
    _write_report(root)
    with pytest.raises(BundleError, match="the connect URL is"):
        run_bundle(_args(output="b.zip"))


def test_config_with_no_url_for_a_product_of_the_run_fails(root):
    toml = (root / "vip.toml").read_text(encoding="utf-8")
    (root / "vip.toml").write_text(
        toml.replace("https://connect.example.com", ""), encoding="utf-8"
    )
    _write_report(root)
    with pytest.raises(BundleError, match="the connect URL is not set in the configuration"):
        run_bundle(_args(output="b.zip"))


def test_config_with_a_url_for_a_product_that_the_run_did_not_have_fails(tmp_path):
    config = VIPConfig()
    config.workbench.url = "https://workbench.example.com"
    results = json.dumps({"products": {"workbench": {"url": ""}, "connect": {"url": ""}}})
    with pytest.raises(BundleError, match=r"not set in results\.json"):
        bundle_module._check_config_matches(config, tmp_path / "vip.toml", results.encode())


def test_inline_connection_string_blocks_bundle_when_the_env_variable_replaces_it(
    root, monkeypatch
):
    # load_config gives the value of the variable, not the inline string.
    toml = (root / "vip.toml").read_text(encoding="utf-8")
    (root / "vip.toml").write_text(
        toml.replace("[data_sources.pg]", '[data_sources.pg]\nconnection_string_env = "PG_CONN"'),
        encoding="utf-8",
    )
    monkeypatch.setenv("PG_CONN", "postgresql://other:OTHER-db-password-9@db:5432/app")
    _write_report(root, results_extra="SECRET-db-password")
    with pytest.raises(BundleError, match=r"data_sources\.pg\.connection_string"):
        run_bundle(_args(output="b.zip"))


def test_inline_git_token_blocks_bundle_when_the_clone_is_anonymous(root):
    # With auth_method "none", the loaded configuration has no token.
    toml = (root / "vip.toml").read_text(encoding="utf-8")
    (root / "vip.toml").write_text(
        toml.replace("[workbench.git_test]", '[workbench.git_test]\nauth_method = "none"'),
        encoding="utf-8",
    )
    _write_report(root, results_extra="SECRET-git-token")
    with pytest.raises(BundleError, match=r"workbench\.git_test\.token"):
        run_bundle(_args(output="b.zip"))


def test_env_credential_blocks_bundle_when_the_config_has_an_inline_value(root, monkeypatch):
    # The loaded configuration keeps the inline key, so the scan must read
    # the variable directly.
    monkeypatch.setenv("VIP_CONNECT_API_KEY", "ENV-ONLY-CONNECT-KEY-77")
    _write_report(root, results_extra="ENV-ONLY-CONNECT-KEY-77")
    with pytest.raises(BundleError, match="VIP_CONNECT_API_KEY"):
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


def test_directory_with_no_run_names_the_missing_results_first(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(BundleError, match="no results found") as exc:
        run_bundle(_args())
    assert "vip.toml" not in str(exc.value)


def test_summary_says_what_the_auth_cache_of_the_run_holds(root):
    run_bundle(_args(output="b.zip"))
    with zipfile.ZipFile(root / "b.zip") as zf:
        summary = json.loads(zf.read("config-summary.json"))
    assert summary["auth_cache"] == {"session": True, "minted_connect_api_key": True}
    assert "vip bundle" in summary["credential_flags"]


def test_summary_says_when_the_run_left_no_auth_cache(root):
    (root / ".vip-auth-cache.json").unlink()
    (root / ".vip-auth-cache.meta.json").unlink()
    run_bundle(_args(output="b.zip"))
    with zipfile.ZipFile(root / "b.zip") as zf:
        summary = json.loads(zf.read("config-summary.json"))
    assert summary["auth_cache"] == {"session": False, "minted_connect_api_key": False}


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


def test_main_writes_a_bundle_from_real_arguments(root, monkeypatch, capsys):
    # The parser, not a hand-built Namespace, sets each option. A change to an
    # option's action or dest fails here.
    _write_report(root, results_extra="SECRET-auth-password")
    argv = ["vip", "bundle", "--output", "b.zip", "--force", "--allow-match", "auth.password"]
    (root / "b.zip").write_bytes(b"old")
    monkeypatch.setattr(sys, "argv", argv)
    main()
    with zipfile.ZipFile(root / "b.zip") as zf:
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["allowed_matches"] == [
        {"member": "report/results.json", "label": "auth.password"}
    ]
    assert "Bundle written" in capsys.readouterr().out


def test_main_repeats_allow_match(root, monkeypatch):
    _write_report(root, results_extra="SECRET-auth-password SECRET-pm-token")
    argv = ["vip", "bundle", "--output", "b.zip"]
    argv += ["--allow-match", "auth.password", "--allow-match", "package_manager.token"]
    monkeypatch.setattr(sys, "argv", argv)
    main()
    assert (root / "b.zip").is_file()


def test_vip_config_selects_the_configuration_file(root, tmp_path, monkeypatch):
    elsewhere = tmp_path / "conf" / "site.toml"
    elsewhere.parent.mkdir()
    (root / "vip.toml").rename(elsewhere)
    monkeypatch.setenv("VIP_CONFIG", str(elsewhere))
    _write_report(root, results_extra="SECRET-pm-token")
    with pytest.raises(BundleError, match=r"package_manager\.token"):
        run_bundle(_args(output="b.zip"))


_RUN_URL = "https://admin:RUN-URL-PASS-0123@connect.example.com"


def _write_report_with_run_url(root: Path) -> None:
    report = root / "report"
    results = {
        "deployment_name": "Acme Prod",
        "products": {"connect": {"url": _RUN_URL}},
        "results": [],
    }
    _write(report / "results.json", json.dumps(results), RESULTS_MTIME)


def test_no_config_scan_uses_the_product_url_credentials_in_results(root):
    (root / "vip.toml").unlink()
    _write_report_with_run_url(root)
    with pytest.raises(BundleError, match=r"results\.json connect\.url password"):
        run_bundle(_args(output="b.zip", no_config=True))


def test_config_scan_uses_the_product_url_credentials_in_results(root):
    # vip.toml has the same host with no userinfo, so it passes the match check.
    _write_report_with_run_url(root)
    with pytest.raises(BundleError, match=r"results\.json connect\.url password"):
        run_bundle(_args(output="b.zip"))


def test_bad_auth_cache_stops_the_bundle(root):
    (root / ".vip-auth-cache.meta.json").write_text('{"api_key": "x"', encoding="utf-8")
    with pytest.raises(BundleError, match="could not read the auth cache file"):
        run_bundle(_args(output="b.zip"))


def _write_run(root: Path, products: dict, base_urls=None, settings=None) -> None:
    results = {"deployment_name": "Acme Prod", "products": products, "results": []}
    if base_urls is not None:
        results["base"] = {
            "deployment_name": "Acme Prod",
            "products": {name: {"url": url} for name, url in base_urls.items()},
        }
    if settings is not None:
        results["settings"] = settings
    _write(root / "report" / "results.json", json.dumps(results), RESULTS_MTIME)


def _proxy_settings(url: str, credentials: bool) -> dict:
    return {
        "insecure": False,
        "ca_bundle": None,
        "auth": {"provider": "password", "idp": ""},
        "proxy": {
            "url": url,
            "no_proxy": [],
            "enabled": True,
            "trust_env": True,
            "effective": [{"url": url, "credentials": credentials}],
        },
    }


def _summary(zip_path: Path) -> dict:
    with zipfile.ZipFile(zip_path) as zf:
        return json.loads(zf.read("config-summary.json"))


def test_url_override_passes_when_the_config_matches_the_recorded_base(root):
    _write_run(
        root,
        {"connect": {"url": "https://connect.override.example.com"}},
        base_urls={"connect": "https://connect.example.com"},
    )
    run_bundle(_args(output="b.zip"))
    assert _summary(root / "b.zip")["connect"]["url"] == "https://connect.override.example.com"


def test_url_override_does_not_excuse_a_config_that_is_not_the_base(root):
    # vip.toml has connect.example.com, and the flag happened to use that host,
    # but the run started from a file that declared another one.
    _write_run(
        root,
        {"connect": {"url": "https://connect.example.com"}},
        base_urls={"connect": "https://a.example.com"},
    )
    with pytest.raises(BundleError, match="the connect URL is"):
        run_bundle(_args(output="b.zip"))


def test_base_deployment_name_is_compared_too(root):
    _write_run(root, {"connect": {"url": "https://connect.example.com"}}, base_urls={})
    results = json.loads((root / "report" / "results.json").read_text(encoding="utf-8"))
    results["base"]["deployment_name"] = "Acme Staging"
    _write(root / "report" / "results.json", json.dumps(results), RESULTS_MTIME)
    with pytest.raises(BundleError, match="the deployment is"):
        run_bundle(_args(output="b.zip"))


def test_base_with_no_url_for_a_product_the_config_has_fails(root):
    _write_run(
        root,
        {"connect": {"url": "https://connect.example.com"}},
        base_urls={"connect": ""},
    )
    with pytest.raises(BundleError, match="the connect URL is"):
        run_bundle(_args(output="b.zip"))


def test_no_config_bundle_ignores_the_recorded_base(root):
    _write_run(
        root,
        {"connect": {"url": "https://connect.example.com"}},
        base_urls={"connect": "https://a.example.com"},
    )
    run_bundle(_args(output="b.zip", no_config=True))
    assert (root / "b.zip").is_file()


def test_summary_describes_the_settings_the_run_used(root):
    settings = {
        "insecure": True,
        "ca_bundle": "/etc/ca.pem",
        "auth": {"provider": "saml", "idp": "keycloak"},
        "proxy": {
            "url": "http://override-proxy:3128",
            "no_proxy": ["b.example.com"],
            "enabled": True,
            "trust_env": False,
            "effective": [],
        },
    }
    _write_run(
        root,
        {
            "connect": {
                "url": "https://connect.example.com",
                "enabled": True,
                "version": "2026.06.0",
            }
        },
        settings=settings,
    )
    run_bundle(_args(output="b.zip"))
    summary = _summary(root / "b.zip")
    assert summary["insecure"] is True
    assert summary["ca_bundle"] == "/etc/ca.pem"
    assert summary["auth"]["provider"] == "saml"
    assert summary["auth"]["idp"] == "keycloak"
    assert summary["proxy"] == {
        "url": "http://override-proxy:3128",
        "no_proxy": ["b.example.com"],
        "enabled": True,
        "trust_env": False,
    }
    assert summary["connect"]["version"] == "2026.06.0"


def test_proxy_credentials_the_bundle_cannot_see_stop_the_bundle(root):
    _write_run(
        root,
        {"connect": {"url": "https://connect.example.com"}},
        settings=_proxy_settings("http://override-proxy:3128", credentials=True),
    )
    with pytest.raises(BundleError, match=r"http://override-proxy:3128.*HTTPS_PROXY"):
        run_bundle(_args(output="b.zip"))
    assert _leftovers(root) == []


def test_proxy_credentials_stop_a_no_config_bundle_too(root):
    _write_run(
        root,
        {"connect": {"url": "https://connect.example.com"}},
        settings=_proxy_settings("http://override-proxy:3128", credentials=True),
    )
    with pytest.raises(BundleError, match="override-proxy:3128"):
        run_bundle(_args(output="b.zip", no_config=True))


def test_proxy_credentials_known_from_the_environment_are_scanned_for(root, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://user:OVERRIDE-PROXY-PASS@override-proxy:3128")
    _write_run(
        root,
        {"connect": {"url": "https://connect.example.com"}},
        settings=_proxy_settings("http://override-proxy:3128", credentials=True),
    )
    run_bundle(_args(output="b.zip"))
    assert (root / "b.zip").is_file()
    results = json.loads((root / "report" / "results.json").read_text(encoding="utf-8"))
    results["note"] = "OVERRIDE-PROXY-PASS"
    _write(root / "report" / "results.json", json.dumps(results), RESULTS_MTIME)
    with pytest.raises(BundleError, match="HTTPS_PROXY password"):
        run_bundle(_args(output="c.zip"))


def test_proxy_credentials_known_from_the_config_file_pass(root):
    _write_run(
        root,
        {"connect": {"url": "https://connect.example.com"}},
        settings=_proxy_settings("http://proxy:8080", credentials=True),
    )
    run_bundle(_args(output="b.zip"))
    assert (root / "b.zip").is_file()


def test_run_without_proxy_credentials_needs_nothing_extra(root):
    _write_run(
        root,
        {"connect": {"url": "https://connect.example.com"}},
        settings=_proxy_settings("http://override-proxy:3128", credentials=False),
    )
    run_bundle(_args(output="b.zip"))
    assert (root / "b.zip").is_file()


def _token_only_proxy(root: Path) -> None:
    toml = (root / "vip.toml").read_text(encoding="utf-8")
    (root / "vip.toml").write_text(
        re.sub(r'url = "http://puser:[^"]*"', 'url = "PROXY-TOKEN-0123@proxy.example:8080"', toml),
        encoding="utf-8",
    )


def test_summary_redacts_a_token_only_scheme_less_proxy(root):
    _token_only_proxy(root)
    run_bundle(_args(output="b.zip"))
    with zipfile.ZipFile(root / "b.zip") as zf:
        summary = json.loads(zf.read("config-summary.json"))
    assert summary["proxy"]["url"] == "http://proxy.example:8080"
    assert "PROXY-TOKEN-0123" not in json.dumps(summary)


def test_scan_knows_a_token_only_scheme_less_proxy(root):
    _token_only_proxy(root)
    _write_report(root, results_extra="PROXY-TOKEN-0123")
    with pytest.raises(BundleError, match=r"proxy\.url user"):
        run_bundle(_args(output="b.zip"))


def _base_check(tmp_path, file_url: str, base_file_url: str | None = None) -> None:
    from vip.cli.verify import _base_identity
    from vip.config import load_config

    path = tmp_path / "vip.toml"
    path.write_text(f'[connect]\nurl = "{file_url}"\n', encoding="utf-8")
    base_path = tmp_path / "base.toml"
    base_path.write_text(f'[connect]\nurl = "{base_file_url or file_url}"\n', encoding="utf-8")
    results = json.dumps(
        {
            "products": {"connect": {"url": "https://connect.override.example.com"}},
            "base": _base_identity(base_path),
        }
    )
    bundle_module._check_config_matches(load_config(path), path, results.encode())


@pytest.mark.parametrize(
    "url",
    [
        "TOKEN-ABC-0123@connect.example.com",
        "https://user:pass@connect.example.com/x",
        "https://connect.example.com:8443/x",
    ],
)
def test_config_matches_the_base_recorded_from_itself(tmp_path, url):
    _base_check(tmp_path, url)


def test_config_for_another_host_does_not_match_the_base(tmp_path):
    with pytest.raises(BundleError, match="the connect URL is"):
        _base_check(tmp_path, "https://staging.example.com", "https://prod.example.com")


@pytest.mark.parametrize(
    "url",
    [
        "https://prod.example.com/@team",
        "https://connect.example.com/?q=a@b",
        "https://admin:Ab/c123x@connect.example.com/p",
        "https://Tok#en-0123@connect.example.com",
    ],
)
def test_ambiguous_base_url_stops_the_bundle(tmp_path, url):
    with pytest.raises(BundleError, match="cannot tell which"):
        _base_check(tmp_path, url)


def test_ambiguous_base_cannot_accept_a_different_config(tmp_path):
    with pytest.raises(BundleError, match="cannot tell which"):
        _base_check(tmp_path, "https://staging.example.com/@team", "https://prod.example.com/@team")


def test_every_credentialed_effective_proxy_must_be_visible(root, monkeypatch):
    settings = _proxy_settings("http://gw-a:3128", credentials=True)
    settings["proxy"]["effective"].append({"url": "http://gw-b:3128", "credentials": True})
    _write_run(root, {"connect": {"url": "https://connect.example.com"}}, settings=settings)
    monkeypatch.setenv("HTTPS_PROXY", "http://u:PROXY-PASS-A-0123@gw-a:3128")
    with pytest.raises(BundleError, match=r"gw-b:3128"):
        run_bundle(_args(output="b.zip"))
    monkeypatch.setenv("HTTP_PROXY", "http://u:PROXY-PASS-B-0123@gw-b:3128")
    run_bundle(_args(output="b.zip"))
    assert (root / "b.zip").is_file()


def test_effective_proxy_without_credentials_needs_nothing(root):
    settings = _proxy_settings("http://gw-a:3128", credentials=False)
    settings["proxy"]["effective"].append({"url": "http://gw-b:3128", "credentials": True})
    settings["proxy"]["effective"][1]["credentials"] = False
    _write_run(root, {"connect": {"url": "https://connect.example.com"}}, settings=settings)
    run_bundle(_args(output="b.zip"))
    assert (root / "b.zip").is_file()


def test_run_without_a_url_override_matches_a_config_with_an_at_in_the_path(tmp_path):
    from vip.config import load_config

    url = "https://prod.example.com/@team"
    path = tmp_path / "vip.toml"
    path.write_text(f'[connect]\nurl = "{url}"\n', encoding="utf-8")
    # A run with only --insecure records no base, so main's comparison applies.
    results = json.dumps({"products": {"connect": {"url": url}}})
    bundle_module._check_config_matches(load_config(path), path, results.encode())


def test_ambiguous_url_message_never_suggests_no_config(tmp_path):
    with pytest.raises(BundleError) as excinfo:
        _base_check(tmp_path, "https://prod.example.com/@team")
    message = str(excinfo.value)
    assert "Percent-encode the @" in message
    assert "--no-config" not in message
