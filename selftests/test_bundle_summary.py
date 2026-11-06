"""Tests for the ``vip bundle`` configuration summary and secret list."""

from __future__ import annotations

import dataclasses
import json
import types
import typing
from typing import Any

import pytest

from vip.bundle.summary import (
    EXCLUDED_FIELDS,
    SECRET_FIELDS,
    SUMMARIZED_FIELDS,
    auth_cache_secrets,
    build_config_summary,
    secret_values,
    strip_url_userinfo,
)
from vip.config import (
    AuthConfig,
    ConnectConfig,
    DataSourceEntry,
    GitTestConfig,
    PackageManagerConfig,
    VIPConfig,
    WorkbenchConfig,
)
from vip.proxy import ProxyConfig

# Every VIP_* variable that VIPConfig or the bundle reads. A developer's own
# shell must not change what these tests see.
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

# One distinct value per credential source, so a test can name the one that leaked.
SECRETS = {
    "connect.api_key": "SECRET-connect-api-key",
    "workbench.api_key": "SECRET-workbench-api-key",
    "workbench.git_test.token": "SECRET-git-token",
    "clone_url user": "SECRET-git-user-token",
    "clone_url query": "SECRET-git-query-token",
    "package_manager.token": "SECRET-pm-token",
    "auth.password": "SECRET-auth-password",
    "connection_string password": "SECRET-db-password",
    "connect.url password": "SECRET-connect-url-password",
    "proxy.url password": "SECRET-proxy-password",
}


@pytest.fixture(autouse=True)
def _no_vip_env(monkeypatch):
    for var in _VIP_SECRET_ENV:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def full_config() -> VIPConfig:
    return VIPConfig(
        deployment_name="Acme Prod",
        connect=ConnectConfig(
            url=f"https://cuser:{SECRETS['connect.url password']}@connect.example.com",
            api_key=SECRETS["connect.api_key"],
        ),
        workbench=WorkbenchConfig(
            url="https://workbench.example.com",
            api_key=SECRETS["workbench.api_key"],
            git_test=GitTestConfig(
                clone_url=(
                    f"https://{SECRETS['clone_url user']}@github.com/org/repo.git"
                    f"?access_token={SECRETS['clone_url query']}"
                ),
                token=SECRETS["workbench.git_test.token"],
            ),
        ),
        package_manager=PackageManagerConfig(
            url="https://pm.example.com", token=SECRETS["package_manager.token"]
        ),
        auth=AuthConfig(username="alice", password=SECRETS["auth.password"]),
        data_sources=[
            DataSourceEntry(
                name="pg",
                type="postgres",
                connection_string=(
                    f"postgresql://dbuser:{SECRETS['connection_string password']}@db:5432/app"
                ),
            )
        ],
        proxy=ProxyConfig(url=f"http://puser:{SECRETS['proxy.url password']}@proxy:8080"),
    )


def _walk_config_fields(cls: Any, prefix: str = "") -> set[str]:
    """Return the dotted path of every leaf field of a config dataclass.

    This helper lives in the test, not in the module, so that the test does
    not trust the code that it checks. config.py uses postponed annotations,
    so the field types come from typing.get_type_hints.
    """
    hints = typing.get_type_hints(cls)
    paths: set[str] = set()
    for f in dataclasses.fields(cls):
        hint = hints[f.name]
        args = typing.get_args(hint)
        origin = typing.get_origin(hint)
        path = prefix + f.name
        if dataclasses.is_dataclass(hint):
            paths |= _walk_config_fields(hint, path + ".")
        elif origin is list and args and dataclasses.is_dataclass(args[0]):
            paths |= _walk_config_fields(args[0], path + "[].")
        elif origin in (typing.Union, types.UnionType) and any(
            dataclasses.is_dataclass(a) for a in args
        ):
            inner = next(a for a in args if dataclasses.is_dataclass(a))
            paths |= _walk_config_fields(inner, path + ".")
        else:
            paths.add(path)
    return paths


# Summary keys whose value is a plain dict, not a nested section.
_DICT_VALUED_KEYS = {"node_pool_profiles", "profile_cpu_limit", "profile_memory_limit_gib"}


def _summary_paths(node: dict, prefix: str = "") -> set[str]:
    """Return the dotted path of every leaf key in a summary, without ``*_set`` keys."""
    paths: set[str] = set()
    for key, value in node.items():
        path = prefix + key
        if key.endswith("_set"):
            continue
        if isinstance(value, dict) and key not in _DICT_VALUED_KEYS:
            paths |= _summary_paths(value, path + ".")
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            paths |= _summary_paths(value[0], path + "[].")
        else:
            paths.add(path)
    return paths


def test_every_config_field_is_classified():
    assert _walk_config_fields(VIPConfig) == SUMMARIZED_FIELDS | EXCLUDED_FIELDS
    assert not (SUMMARIZED_FIELDS & EXCLUDED_FIELDS)
    assert SECRET_FIELDS <= EXCLUDED_FIELDS


def test_summary_has_exactly_the_summarized_fields(full_config):
    assert _summary_paths(build_config_summary(full_config)) == SUMMARIZED_FIELDS


def _config_classes(cls: Any, prefix: str = "") -> list[tuple[Any, str]]:
    """Return ``(class, dotted prefix)`` for *cls* and every config dataclass under it."""
    found = [(cls, prefix)]
    hints = typing.get_type_hints(cls)
    for f in dataclasses.fields(cls):
        hint = hints[f.name]
        args = typing.get_args(hint)
        inner = next((a for a in (hint, *args) if dataclasses.is_dataclass(a)), None)
        if inner is not None:
            suffix = "[]." if typing.get_origin(hint) is list else "."
            found += _config_classes(inner, prefix + f.name + suffix)
    return found


# Field values that __post_init__ needs before the other fields keep their value.
_REQUIRED_VALUES = {GitTestConfig: {"auth_method": "https-token"}}


def test_every_repr_masked_field_is_a_secret():
    # A config class that hides a field in __repr__ treats it as a secret.
    # Every str field gets a distinct sentinel, so a new hidden field is found.
    classes = _config_classes(VIPConfig)
    known = {ConnectConfig, WorkbenchConfig, GitTestConfig, PackageManagerConfig, AuthConfig}
    assert known | {DataSourceEntry} <= {cls for cls, _ in classes}
    hidden: set[str] = set()
    for cls, prefix in classes:
        hints = typing.get_type_hints(cls)
        values = {
            f.name: f"SENTINEL-{prefix}{f.name}"
            for f in dataclasses.fields(cls)
            if f.init and hints[f.name] is str
        }
        values.update(_REQUIRED_VALUES.get(cls, {}))
        text = repr(cls(**values))
        hidden |= {
            prefix + name
            for name, value in values.items()
            if value.startswith("SENTINEL-") and value not in text
        }
    assert hidden == SECRET_FIELDS


_SET_ONE_SECRET = {
    "connect.api_key": lambda v: VIPConfig(connect=ConnectConfig(api_key=v)),
    "workbench.api_key": lambda v: VIPConfig(workbench=WorkbenchConfig(api_key=v)),
    "workbench.git_test.token": lambda v: VIPConfig(
        workbench=WorkbenchConfig(git_test=GitTestConfig(token=v))
    ),
    "package_manager.token": lambda v: VIPConfig(package_manager=PackageManagerConfig(token=v)),
    "auth.password": lambda v: VIPConfig(auth=AuthConfig(password=v)),
    "data_sources[].connection_string": lambda v: VIPConfig(
        data_sources=[DataSourceEntry(name="db", connection_string=v)]
    ),
}


@pytest.mark.parametrize("path", sorted(SECRET_FIELDS))
def test_each_secret_field_is_in_secret_values(path):
    # A new entry in SECRET_FIELDS needs a builder here, and secret_values must return it.
    config = _SET_ONE_SECRET[path]("SENTINEL-VALUE-0123")
    assert "SENTINEL-VALUE-0123" in {value for _, value in secret_values(config)}


def test_every_secret_field_has_a_builder():
    assert set(_SET_ONE_SECRET) == SECRET_FIELDS


def test_summary_has_no_secret_values(full_config):
    text = json.dumps(build_config_summary(full_config))
    for value in SECRETS.values():
        assert value not in text
    assert "cuser" not in text
    assert "puser" not in text
    assert "dbuser" not in text
    assert "alice" not in text


def test_summary_reports_secret_presence(full_config):
    s = build_config_summary(full_config)
    assert s["connect"]["api_key_set"] is True
    assert s["workbench"]["api_key_set"] is True
    assert s["package_manager"]["token_set"] is True
    assert s["auth"]["password_set"] is True
    assert s["workbench"]["git_test"]["token_set"] is True
    assert s["data_sources"] == [{"name": "pg", "type": "postgres", "connection_string_set": True}]
    assert "username" not in s["auth"]


def test_summary_keeps_clone_url_path(full_config):
    s = build_config_summary(full_config)
    assert s["workbench"]["git_test"]["clone_url"] == "https://github.com/org/repo.git"
    assert s["proxy"]["url"] == "http://proxy:8080"
    assert s["connect"]["url"] == "https://connect.example.com"


def test_summary_without_git_test():
    assert build_config_summary(VIPConfig())["workbench"]["git_test"] is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://x-access-token:SECRET@github.com/org/repo.git",
            "https://github.com/org/repo.git",
        ),
        ("https://TOKEN@github.com/org/repo.git", "https://github.com/org/repo.git"),
        ("https://github.com/org/repo.git", "https://github.com/org/repo.git"),
        ("https://github.com/org/repo.git?access_token=T#frag", "https://github.com/org/repo.git"),
        ("http://u:p@[::1]:8080/x", "http://[::1]:8080/x"),
        ("x-access-token:SECRET@github.com/org/repo.git", "github.com/org/repo.git"),
        ("git@github.com:org/repo.git", "git@github.com:org/repo.git"),
        ("", ""),
    ],
)
def test_strip_url_userinfo(url, expected):
    assert strip_url_userinfo(url) == expected


def test_secret_values_cover_every_source(full_config, tmp_path):
    meta = tmp_path / ".vip-auth-cache.meta.json"
    meta.write_text(json.dumps({"api_key": "MINTED-KEY-0001"}), encoding="utf-8")
    state = tmp_path / ".vip-auth-cache.json"
    state.write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "session", "value": "COOKIE-VALUE-0123456789"},
                    {"name": "flag", "value": "1"},
                ],
                "origins": [
                    {
                        "origin": "https://connect.example.com",
                        "localStorage": [{"name": "token", "value": "LOCAL-STORAGE-0123456789"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cache = auth_cache_secrets(state) + auth_cache_secrets(meta)
    values = {value for _, value in secret_values(full_config, cache)}
    assert set(SECRETS.values()) <= values
    assert {"MINTED-KEY-0001", "COOKIE-VALUE-0123456789", "LOCAL-STORAGE-0123456789"} <= values
    assert full_config.data_sources[0].connection_string in values
    assert "1" not in values
    assert "" not in values
    # A user name next to a password is not a credential, except in the Git clone URL.
    assert not {"cuser", "puser", "dbuser"} & values


@pytest.mark.parametrize(
    "clone_url",
    [
        "https://GIT-TOKEN-0123456789:x-oauth-basic@github.com/org/repo.git",
        "https://GIT-TOKEN-0123456789:@github.com/org/repo.git",
        "x-access-token:GIT-TOKEN-0123456789@github.com/org/repo.git",
    ],
)
def test_secret_values_find_the_clone_url_token_in_each_form(clone_url):
    config = VIPConfig(workbench=WorkbenchConfig(git_test=GitTestConfig(clone_url=clone_url)))
    assert "GIT-TOKEN-0123456789" in {value for _, value in secret_values(config)}
    assert "GIT-TOKEN" not in json.dumps(build_config_summary(config))


def test_secret_values_labels_name_the_source(full_config):
    labels = {value: label for label, value in secret_values(full_config)}
    assert labels[SECRETS["auth.password"]] == "auth.password"
    assert labels[SECRETS["clone_url user"]] == "workbench.git_test.clone_url credentials"


def test_secret_values_read_env_only_secrets(monkeypatch):
    monkeypatch.setenv("VIP_GIT_TOKEN", "ENV-GIT-TOKEN")
    monkeypatch.setenv("VIP_TEST_TOTP_SECRET", "ENV-TOTP-SEED")
    monkeypatch.setenv("HTTPS_PROXY", "http://u:ENV-PROXY-PASS@proxy:3128")
    monkeypatch.setenv("VIP_CONNECT_API_KEY", "ENV-CONNECT-KEY")
    values = {value for _, value in secret_values(VIPConfig())}
    assert {"ENV-GIT-TOKEN", "ENV-TOTP-SEED", "ENV-PROXY-PASS", "ENV-CONNECT-KEY"} <= values


def test_secret_values_split_key_value_connection_string():
    conn = (
        "Driver=Snowflake;Server=db;Uid=sa;Pwd=ODBC-PASS;token=SNOW-TOKEN-01;"
        "AccountKey=AZURE-KEY-01==;Password={pa;ss-0123};"
    )
    config = VIPConfig(data_sources=[DataSourceEntry(name="db", connection_string=conn)])
    labels = {value: label for label, value in secret_values(config)}
    assert labels[conn] == "data_sources.db.connection_string"
    assert labels["ODBC-PASS"] == "data_sources.db.connection_string pwd"
    assert labels["SNOW-TOKEN-01"] == "data_sources.db.connection_string token"
    assert labels["AZURE-KEY-01=="] == "data_sources.db.connection_string accountkey"
    assert labels["pa;ss-0123"] == "data_sources.db.connection_string password"
    assert "sa" not in labels


def test_auth_cache_secrets_skip_missing_or_bad_files(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    listed = tmp_path / "list.json"
    listed.write_text("[]", encoding="utf-8")
    for path in (bad, listed, tmp_path / "absent.json"):
        assert auth_cache_secrets(path) == []
