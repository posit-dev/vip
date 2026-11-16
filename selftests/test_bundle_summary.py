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
    SECRET_ENV_VARS,
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
from vip.errors import BundleError
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


_STR_TYPES = (str, str | None)
_LIST_TYPES = (list[str], list[str] | None)
_DICT_TYPES = (dict[str, str], dict[str, str] | None)


def _sentinel_values(cls: type, prefix: str) -> dict[str, tuple[object, str]]:
    """Return ``{field: (value, sentinel)}`` for each init field that can hold a str.

    A str field gets the sentinel. A list field gets a list that holds it,
    and a dict field gets a dict with it as the value.
    """
    hints = typing.get_type_hints(cls)
    found: dict[str, tuple[object, str]] = {}
    for f in dataclasses.fields(cls):
        sentinel = f"SENTINEL-{prefix}{f.name}"
        hint = hints[f.name]
        if not f.init:
            continue
        if hint in _STR_TYPES:
            found[f.name] = (sentinel, sentinel)
        elif hint in _LIST_TYPES:
            found[f.name] = ([sentinel], sentinel)
        elif hint in _DICT_TYPES:
            found[f.name] = ({"key": sentinel}, sentinel)
    return found


def test_sentinel_values_cover_str_list_and_dict_fields():
    @dataclasses.dataclass
    class Sample:
        name: str = ""
        token: str | None = None
        hosts: list[str] = dataclasses.field(default_factory=list)
        keys: list[str] | None = None
        headers: dict[str, str] = dataclasses.field(default_factory=dict)
        count: int = 0
        limits: dict[str, float] = dataclasses.field(default_factory=dict)

    assert _sentinel_values(Sample, "s.") == {
        "name": ("SENTINEL-s.name", "SENTINEL-s.name"),
        "token": ("SENTINEL-s.token", "SENTINEL-s.token"),
        "hosts": (["SENTINEL-s.hosts"], "SENTINEL-s.hosts"),
        "keys": (["SENTINEL-s.keys"], "SENTINEL-s.keys"),
        "headers": ({"key": "SENTINEL-s.headers"}, "SENTINEL-s.headers"),
    }


def test_every_repr_masked_field_is_a_secret():
    # A config class that hides a field in __repr__ treats it as a secret.
    # Every field that can hold a str, in a list, or in a dict gets a distinct
    # sentinel, so a new hidden field is found.
    classes = _config_classes(VIPConfig)
    known = {ConnectConfig, WorkbenchConfig, GitTestConfig, PackageManagerConfig, AuthConfig}
    assert known | {DataSourceEntry} <= {cls for cls, _ in classes}
    hidden: set[str] = set()
    for cls, prefix in classes:
        required = _REQUIRED_VALUES.get(cls, {})
        sentinels = {
            name: pair
            for name, pair in _sentinel_values(cls, prefix).items()
            if name not in required
        }
        text = repr(cls(**{name: value for name, (value, _) in sentinels.items()}, **required))
        hidden |= {prefix + name for name, (_, s) in sentinels.items() if s not in text}
    assert hidden == SECRET_FIELDS


def test_fields_left_out_of_the_summary_that_are_not_secrets_are_pinned():
    # The scan looks only for SECRET_FIELDS. A new field here is left out of
    # the summary but is not scanned, so it must be a reviewed choice.
    assert {
        "auth.username",
        "connect.url_scheme_inferred",
        "workbench.url_scheme_inferred",
        "package_manager.url_scheme_inferred",
    } == EXCLUDED_FIELDS - SECRET_FIELDS


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


def test_auth_cache_secrets_skip_login_names(tmp_path):
    # Okta keeps the login name in the "ln" cookie. Test output often prints
    # that name, and a login name is not a credential.
    state = tmp_path / ".vip-auth-cache.json"
    state.write_text(
        json.dumps(
            {
                "cookies": [
                    {"name": "ln", "value": "test.user@example.com"},
                    {"name": "ln2", "value": "test.user%40example.com"},
                    {"name": "sid", "value": "a1b2c3@example-0123456789"},
                ],
                "origins": [
                    {
                        "origin": "https://login.example.com",
                        "localStorage": [{"name": "user", "value": "test.user@example.com"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert auth_cache_secrets(state) == [("auth cache cookie sid", "a1b2c3@example-0123456789")]


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
    assert labels[SECRETS["clone_url user"]] == "workbench.git_test.clone_url user"
    assert labels[SECRETS["clone_url query"]] == "workbench.git_test.clone_url query access_token"


def test_clone_url_user_and_password_have_their_own_labels():
    # --allow-match for a false match on a public user name must not also
    # let the token through.
    url = "https://x-access-token:GIT-TOKEN-0123456789@github.com/org/repo.git"
    config = VIPConfig(workbench=WorkbenchConfig(git_test=GitTestConfig(clone_url=url)))
    labels = {value: label for label, value in secret_values(config)}
    assert labels["x-access-token"] == "workbench.git_test.clone_url user"
    assert labels["GIT-TOKEN-0123456789"] == "workbench.git_test.clone_url password"


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


def test_auth_cache_secrets_skip_a_missing_file(tmp_path):
    assert auth_cache_secrets(tmp_path / "absent.json") == []


_GOOD_CACHE = json.dumps({"cookies": [{"name": "sid", "value": "COOKIE-VALUE-0123456789"}]})


@pytest.mark.parametrize(
    "data",
    [
        b"not json",
        _GOOD_CACHE[:-3].encode(),  # cut before the closing brackets
        b"\xef\xbb\xbf" + _GOOD_CACHE.encode(),  # UTF-8 BOM
        _GOOD_CACHE.encode("utf-16"),
        b"[]",
        b'{"cookies": 5}',
        b'{"cookies": ["sid"]}',
        b'{"origins": {"localStorage": []}}',
        b'{"origins": [{"localStorage": 5}]}',
    ],
)
def test_auth_cache_file_that_cannot_be_used_raises(tmp_path, data):
    path = tmp_path / ".vip-auth-cache.json"
    path.write_bytes(data)
    with pytest.raises(BundleError, match="could not read the auth cache file"):
        auth_cache_secrets(path)


def test_auth_cache_directory_raises(tmp_path):
    with pytest.raises(BundleError, match="could not read the auth cache file"):
        auth_cache_secrets(tmp_path)


def test_auth_cache_labels_name_the_domain_and_the_origin(tmp_path):
    state = tmp_path / ".vip-auth-cache.json"
    cookies = [
        {"name": "sid", "domain": "a.example.com", "value": "COOKIE-A-0123456789"},
        {"name": "sid", "domain": "b.example.com", "value": "COOKIE-B-0123456789"},
    ]
    origins = [
        {
            "origin": "https://a.example.com",
            "localStorage": [{"name": "t", "value": "LOCAL-A-0123456789"}],
        }
    ]
    state.write_text(json.dumps({"cookies": cookies, "origins": origins}), encoding="utf-8")
    assert auth_cache_secrets(state) == [
        ("auth cache cookie a.example.com sid", "COOKIE-A-0123456789"),
        ("auth cache cookie b.example.com sid", "COOKIE-B-0123456789"),
        ("auth cache localStorage https://a.example.com t", "LOCAL-A-0123456789"),
    ]


@pytest.mark.parametrize(
    "value",
    [
        "user:PASSWORD-0123456789@host.example.com",
        "https://user:PASSWORD-0123@host.example.com",
        "token=ABCDEFGH01234567&email=a@example.com",
        "TOKEN-0123456789|test.user@example.com",
        'prefix "test.user@example.com" TOKEN-0123456789',
        "a@b@example.com-0123456789",
        "tok@en-0123456789@example.com",
        "no-at-sign-0123456789.example.com",
        '{"login":"test.user@example.com","t":"abc"}',
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ2aXAifQ.signature",
    ],
)
def test_auth_cache_value_that_is_more_than_an_email_is_a_secret(tmp_path, value):
    state = tmp_path / ".vip-auth-cache.json"
    state.write_text(json.dumps({"cookies": [{"name": "sid", "value": value}]}), encoding="utf-8")
    assert auth_cache_secrets(state) == [("auth cache cookie sid", value)]


def test_auth_cache_value_floor_is_exactly_16_characters(tmp_path):
    at, below = "a1b2c3d4e5f6g7h8", "a1b2c3d4e5f6g7h"
    state = tmp_path / ".vip-auth-cache.json"
    cookies = [{"name": "at", "value": at}, {"name": "below", "value": below}]
    state.write_text(json.dumps({"cookies": cookies}), encoding="utf-8")
    assert auth_cache_secrets(state) == [("auth cache cookie at", at)]


def test_email_shaped_password_and_minted_key_are_secrets(tmp_path):
    # The login name rule is only for cookies and localStorage values.
    meta = tmp_path / ".vip-auth-cache.meta.json"
    meta.write_text(json.dumps({"api_key": "svc.account@example.com"}), encoding="utf-8")
    config = VIPConfig(auth=AuthConfig(password="svc.user@example.com"))
    values = {value for _, value in secret_values(config, auth_cache_secrets(meta))}
    assert {"svc.user@example.com", "svc.account@example.com"} <= values


def test_each_product_url_credential_is_a_secret_and_is_not_in_the_summary():
    config = VIPConfig(
        connect=ConnectConfig(url="https://u:URL-PASS-connect1@connect.example.com"),
        workbench=WorkbenchConfig(url="https://u:URL-PASS-workbench1@wb.example.com"),
        package_manager=PackageManagerConfig(url="https://u:URL-PASS-pm1@pm.example.com"),
    )
    values = {value for _, value in secret_values(config)}
    assert {"URL-PASS-connect1", "URL-PASS-workbench1", "URL-PASS-pm1"} <= values
    assert "URL-PASS" not in json.dumps(build_config_summary(config))


def test_url_credential_is_a_secret_raw_and_percent_decoded():
    config = VIPConfig(connect=ConnectConfig(url="https://u:p%40ss-0123@connect.example.com"))
    assert {"p%40ss-0123", "p@ss-0123"} <= {value for _, value in secret_values(config)}


_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


@pytest.mark.parametrize("var", _PROXY_VARS)
def test_each_proxy_variable_is_read(monkeypatch, var):
    for other in _PROXY_VARS:
        monkeypatch.delenv(other, raising=False)
    monkeypatch.setenv(var, "http://u:ENV-PROXY-PASS@proxy:3128")
    assert "ENV-PROXY-PASS" in {value for _, value in secret_values(VIPConfig())}


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # urlsplit raises ValueError for this host. It is not a plain host.
        ("http://u:SECRET@[::1/x?token=T", "http://<redacted>/x"),
        # A Git remote with no scheme.
        (
            "x-access-token:SECRET@github.com/org/repo.git?access_token=T#f",
            "github.com/org/repo.git",
        ),
    ],
)
def test_strip_url_userinfo_handles_a_bad_host_and_a_bare_remote(url, expected):
    assert strip_url_userinfo(url) == expected


@pytest.mark.parametrize(
    ("url", "secret", "summary"),
    [
        (
            "https://admin:Abc123#Secret9@connect.example.com",
            "Abc123#Secret9",
            "https://connect.example.com",
        ),
        (
            "https://admin:Abc?123x@connect.example.com/p",
            "Abc?123x",
            "https://connect.example.com/p",
        ),
        (
            "https://admin:Ab/c123x@connect.example.com/p",
            "Ab/c123x",
            "https://connect.example.com/p",
        ),
        ("https://Tok#en-0123@connect.example.com", "Tok#en-0123", "https://connect.example.com"),
    ],
)
def test_password_with_a_raw_delimiter_is_a_secret_and_is_not_in_the_summary(url, secret, summary):
    config = VIPConfig(connect=ConnectConfig(url=url))
    assert secret in {value for _, value in secret_values(config)}
    assert strip_url_userinfo(url) == summary


def test_url_with_an_at_sign_in_the_path_keeps_the_real_password_too():
    # The two parsers differ when the URL holds two "@". The scan looks for both values.
    url = "https://u:REAL-PASS-0123@connect.example.com/a@b"
    values = {value for _, value in secret_values(VIPConfig(connect=ConnectConfig(url=url)))}
    assert "REAL-PASS-0123" in values


@pytest.mark.parametrize(
    ("url", "summary"),
    [
        ("https://admin:Abc123", "https://<redacted>"),
        ("https://connect.example.com:8443/x", "https://connect.example.com:8443/x"),
    ],
)
def test_summary_redacts_a_host_that_is_not_a_plain_host(url, summary):
    assert strip_url_userinfo(url) == summary


def test_each_part_of_a_url_has_its_own_label():
    conn = "postgresql://appuser@db.example.com:5432/app?sslmode=require&password=PG-PASS-0123"
    config = VIPConfig(
        data_sources=[DataSourceEntry(name="pg", connection_string=conn)],
        connect=ConnectConfig(url="https://u:URL-PASS-0123@c.example.com/?token=URL-TOKEN-0123"),
    )
    labels = {value: label for label, value in secret_values(config)}
    assert labels["appuser"] == "data_sources.pg.connection_string user"
    assert labels["PG-PASS-0123"] == "data_sources.pg.connection_string query password"
    assert labels["URL-PASS-0123"] == "connect.url password"
    assert labels["URL-TOKEN-0123"] == "connect.url query token"


_INLINE_FOR_ENV = {
    "VIP_CONNECT_API_KEY": lambda: VIPConfig(connect=ConnectConfig(api_key="INLINE-0123")),
    "VIP_WORKBENCH_API_KEY": lambda: VIPConfig(workbench=WorkbenchConfig(api_key="INLINE-0123")),
    "VIP_PACKAGE_MANAGER_TOKEN": lambda: VIPConfig(
        package_manager=PackageManagerConfig(token="INLINE-0123")
    ),
    "VIP_PM_TOKEN": lambda: VIPConfig(package_manager=PackageManagerConfig(token="INLINE-0123")),
    "VIP_TEST_PASSWORD": lambda: VIPConfig(auth=AuthConfig(password="INLINE-0123")),
    "VIP_GIT_TOKEN": lambda: VIPConfig(
        workbench=WorkbenchConfig(git_test=GitTestConfig(token="INLINE-0123"))
    ),
    "VIP_TEST_TOTP_SECRET": VIPConfig,
}


@pytest.mark.parametrize("var", SECRET_ENV_VARS)
def test_each_env_variable_is_read_next_to_an_inline_value(monkeypatch, var):
    # The configuration keeps the inline value, so only SECRET_ENV_VARS
    # gives the scan the value of the variable.
    monkeypatch.setenv(var, f"ENV-{var}-0123")
    config = _INLINE_FOR_ENV[var]()
    assert f"ENV-{var}-0123" not in repr(dataclasses.asdict(config))
    assert f"ENV-{var}-0123" in {value for _, value in secret_values(config)}


def test_every_env_variable_has_an_inline_builder():
    assert set(_INLINE_FOR_ENV) == set(SECRET_ENV_VARS)
