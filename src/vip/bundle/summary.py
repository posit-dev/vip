"""Allowlisted configuration summary, and the secret values that the bundle must not hold."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeGuard
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from vip.config import VIPConfig

# Dotted paths of every VIPConfig field. selftests/test_bundle_summary.py walks
# VIPConfig and fails when a field is in neither set, so a new field must be
# classified before it can ship.
SECRET_FIELDS = frozenset(
    {
        "connect.api_key",
        "workbench.api_key",
        "workbench.git_test.token",
        "package_manager.token",
        "auth.password",
        "data_sources[].connection_string",
    }
)
EXCLUDED_FIELDS = SECRET_FIELDS | frozenset(
    {
        "auth.username",
        "connect.url_scheme_inferred",
        "workbench.url_scheme_inferred",
        "package_manager.url_scheme_inferred",
    }
)
SUMMARIZED_FIELDS = frozenset(
    {
        "deployment_name",
        "extension_dirs",
        "connect.enabled",
        "connect.url",
        "connect.version",
        "connect.deploy_timeout",
        "workbench.enabled",
        "workbench.url",
        "workbench.version",
        "workbench.session_profiles",
        "workbench.session_count",
        "workbench.job_timeout",
        "workbench.test_packages",
        "workbench.idle_timeout_minutes",
        "workbench.idle_grace_seconds",
        "workbench.extensions.vscode",
        "workbench.extensions.positron",
        "workbench.extensions.jupyterlab",
        "workbench.kubernetes.enabled",
        "workbench.kubernetes.namespace",
        "workbench.kubernetes.node_pool_profiles",
        "workbench.kubernetes.max_sessions",
        "workbench.kubernetes.profile_cpu_limit",
        "workbench.kubernetes.profile_memory_limit_gib",
        "workbench.git_test.clone_url",
        "workbench.git_test.auth_method",
        "workbench.chronicle_data_path",
        "package_manager.enabled",
        "package_manager.url",
        "package_manager.version",
        "auth.provider",
        "auth.idp",
        "runtimes.r_versions",
        "runtimes.python_versions",
        "runtimes.r_excluded_versions",
        "runtimes.python_excluded_versions",
        "performance.page_load_timeout",
        "performance.download_timeout",
        "performance.p95_response_time",
        "performance.avg_response_time",
        "performance.concurrent_requests",
        "performance.disk_usage_max_pct",
        "performance.memory_available_min_pct",
        "performance.load_user_counts",
        "performance.load_max_connections",
        "performance.load_success_rate_threshold",
        "performance.load_test_tool",
        "performance.load_test_duration",
        "performance.load_test_spawn_rate",
        "data_sources[].name",
        "data_sources[].type",
        "email_enabled",
        "monitoring_enabled",
        "chronicle_enabled",
        "security_policy_checks_enabled",
        "insecure",
        "ca_bundle",
        "cert_expiry_warning_days",
        "proxy.url",
        "proxy.no_proxy",
        "proxy.enabled",
        "proxy.trust_env",
    }
)

# Each credential variable that VIP reads. The scan reads them all directly,
# because the loaded configuration holds a variable only if the matching field
# in vip.toml is empty, has git_test=None with no [workbench.git_test] table,
# and never holds the TOTP seed.
SECRET_ENV_VARS = (
    "VIP_CONNECT_API_KEY",
    "VIP_WORKBENCH_API_KEY",
    "VIP_PACKAGE_MANAGER_TOKEN",
    "VIP_PM_TOKEN",
    "VIP_TEST_PASSWORD",
    "VIP_GIT_TOKEN",
    "VIP_TEST_TOTP_SECRET",
)
# httpx reads these when proxy.trust_env is true. They can carry user:pass.
PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
# Query keys whose values are credentials, for example ?access_token= in a clone URL.
SECRET_QUERY_KEYS = frozenset(
    {"access_token", "token", "password", "pwd", "api_key", "apikey", "key", "secret", "sig"}
)
# Short cookie values ("1", "true") match normal report text. Session cookies are long.
MIN_COOKIE_LENGTH = 16
# A value that is only an email address is a login name, not a credential. Okta
# keeps it in the "ln" cookie, and test output often prints it. The pattern
# has no ":", "/", "=", "&", or "|", so a URL with credentials, a query
# string, or a token next to an address stays a secret.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# Connection string keys whose values are credentials. ODBC, JDBC, and Azure use these.
CONNECTION_SECRET_KEYS = SECRET_QUERY_KEYS | frozenset(
    {"accountkey", "sharedaccesskey", "sharedaccesssignature", "privatekey", "private_key"}
)

_USERINFO_RE = re.compile(r"://([^/@]*)@")
# A Git remote with no scheme, for example x-access-token:TOKEN@github.com/org/repo.git.
# The userinfo must hold ":", so git@github.com:org/repo.git does not match.
_BARE_USERINFO_RE = re.compile(r"^([^/@\s:]+:[^/@\s]*)@")
# One key=value part of a connection string. A value in braces or quotes can hold ";".
_KV_PART_RE = re.compile(
    r"""(?:^|;)\s*([A-Za-z_][A-Za-z0-9_ ]*?)\s*=\s*(\{[^}]*\}|"[^"]*"|'[^']*'|[^;]*)"""
)


def strip_url_userinfo(url: str) -> str:
    """Return *url* without userinfo, query, or fragment. Keep the scheme, host, port, and path.

    The host comes from the raw netloc, not ``hostname``, so the brackets of
    an IPv6 address stay. A Git remote with no scheme also loses its
    ``user:token@`` part.
    """
    if not url:
        return url
    if "://" not in url:
        return _BARE_USERINFO_RE.sub("", url).split("?", 1)[0].split("#", 1)[0]
    try:
        parts = urlsplit(url)
    except ValueError:
        stripped = _USERINFO_RE.sub("://", url)
        return stripped.split("?", 1)[0].split("#", 1)[0]
    host = parts.netloc.rpartition("@")[2]
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def _url_credentials(url: str, *, both_parts: bool = False) -> list[tuple[str, str]]:
    """Return ``(part, value)`` for each credential in *url*.

    The part is ``user``, ``password``, or ``query`` (a secret query value).

    With ``user:password``, only the password is a credential, unless
    *both_parts* is set. A Git remote can hold the token in either part, for
    example ``https://<token>:x-oauth-basic@host/...``. With an empty
    password, the user part is the credential, because a Git token is often
    written as ``https://<token>@host/...``. Each value is returned raw and
    percent-decoded.
    """
    if not url:
        return []
    query: list[tuple[str, str]] = []
    if "://" not in url:
        match = _BARE_USERINFO_RE.match(url)
        if match is None:
            return []
        userinfo = match.group(1)
    else:
        try:
            parts = urlsplit(url)
            query = parse_qsl(parts.query)
            userinfo = parts.netloc.rpartition("@")[0]
        except ValueError:
            match = _USERINFO_RE.search(url)
            userinfo = match.group(1) if match else ""
    user, _, password = userinfo.partition(":")
    if both_parts:
        values = [("user", user), ("password", password)]
    else:
        values = [("password", password) if password else ("user", user)]
    values += [("query", value) for key, value in query if key.lower() in SECRET_QUERY_KEYS]
    return [(part, v) for part, value in values for v in (value, unquote(value)) if v]


def _connection_string_parts(conn: str) -> list[tuple[str, str]]:
    """Return ``(key, value)`` for each credential part of a key=value connection string."""
    parts: list[tuple[str, str]] = []
    for key, raw in _KV_PART_RE.findall(conn):
        name = key.strip().lower().replace(" ", "")
        value = raw.strip()
        if len(value) >= 2 and value[0] in "{\"'":
            value = value[1:-1]
        if name in CONNECTION_SECRET_KEYS and value:
            parts.append((name, value))
    return parts


def _connection_string_secrets(label: str, conn: str) -> list[tuple[str, str]]:
    """Return the whole connection string and each credential part of it, with labels."""
    pairs = [(label, conn)]
    pairs += [(f"{label} credentials", v) for _, v in _url_credentials(conn)]
    pairs += [(f"{label} {key}", value) for key, value in _connection_string_parts(conn)]
    return pairs


def _is_cache_secret(value: object) -> TypeGuard[str]:
    """Return True when an auth cache value is long enough and is not a login name."""
    if not isinstance(value, str) or len(value) < MIN_COOKIE_LENGTH:
        return False
    return _EMAIL_RE.fullmatch(unquote(value)) is None


def auth_cache_secrets(path: Path) -> list[tuple[str, str]]:
    """Return ``(label, value)`` for each secret in one auth cache file.

    ``.vip-auth-cache.meta.json`` holds the minted Connect key.
    ``.vip-auth-cache.json`` is a Playwright storage state with cookies and
    localStorage values. A short value or an email address is not a secret. A
    file that is missing or does not parse gives no values.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    pairs: list[tuple[str, str]] = []
    if isinstance(data.get("api_key"), str):
        pairs.append(("auth cache api_key", data["api_key"]))
    for cookie in data.get("cookies") or []:
        value = cookie.get("value") if isinstance(cookie, dict) else None
        if _is_cache_secret(value):
            pairs.append((f"auth cache cookie {cookie.get('name', '')}", value))
    for origin in data.get("origins") or []:
        items = origin.get("localStorage") if isinstance(origin, dict) else None
        for item in items or []:
            value = item.get("value") if isinstance(item, dict) else None
            if _is_cache_secret(value):
                pairs.append((f"auth cache localStorage {item.get('name', '')}", value))
    return pairs


def raw_config_secrets(raw: Any) -> list[tuple[str, str]]:
    """Return the secrets in the parsed text of vip.toml that the loaded configuration can drop.

    The loaded configuration holds the value of ``connection_string_env``
    in place of an inline ``connection_string`` if that variable is set. It
    has no ``workbench.git_test.token`` if ``auth_method`` is ``"none"``. Each
    inline value is a credential in both cases.
    """
    sources = raw.get("data_sources") if isinstance(raw, dict) else None
    pairs: list[tuple[str, str]] = []
    for name, entry in sources.items() if isinstance(sources, dict) else ():
        conn = entry.get("connection_string") if isinstance(entry, dict) else None
        if isinstance(conn, str):
            pairs += _connection_string_secrets(f"data_sources.{name}.connection_string", conn)
    workbench = raw.get("workbench") if isinstance(raw, dict) else None
    git = workbench.get("git_test") if isinstance(workbench, dict) else None
    token = git.get("token") if isinstance(git, dict) else None
    if isinstance(token, str):
        pairs.append(("workbench.git_test.token", token))
    return pairs


def secret_values(
    config: VIPConfig, cache_secrets: Sequence[tuple[str, str]] = ()
) -> list[tuple[str, str]]:
    """Return ``(label, value)`` for every credential that the bundle must not hold.

    *cache_secrets* are extra pairs, such as the ones that
    :func:`auth_cache_secrets` and :func:`raw_config_secrets`
    read. The label names the source of the value, so an error can name it without
    printing the value. Empty values and repeated values are dropped.
    """
    pairs: list[tuple[str, str]] = [
        ("connect.api_key", config.connect.api_key),
        ("workbench.api_key", config.workbench.api_key),
        ("package_manager.token", config.package_manager.token),
        ("auth.password", config.auth.password),
    ]
    git = config.workbench.git_test
    if git is not None:
        pairs.append(("workbench.git_test.token", git.token))
        # Each part has its own label, so that --allow-match for a public user
        # name does not also let the token through.
        pairs += [
            (f"workbench.git_test.clone_url {part}", v)
            for part, v in _url_credentials(git.clone_url, both_parts=True)
        ]
    for ds in config.data_sources:
        pairs += _connection_string_secrets(
            f"data_sources.{ds.name}.connection_string", ds.connection_string
        )
    for product in ("connect", "workbench", "package_manager"):
        url = config.product_config(product).url
        pairs += [(f"{product}.url credentials", v) for _, v in _url_credentials(url)]
    pairs += [("proxy.url credentials", v) for _, v in _url_credentials(config.proxy.url)]
    pairs += [(var, os.environ.get(var, "")) for var in SECRET_ENV_VARS]
    for var in PROXY_ENV_VARS:
        pairs += [(f"{var} credentials", v) for _, v in _url_credentials(os.environ.get(var, ""))]
    pairs += list(cache_secrets)

    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for label, value in pairs:
        if value and value not in seen:
            seen.add(value)
            result.append((label, value))
    return result


def build_config_summary(config: VIPConfig) -> dict[str, Any]:
    """Return the configuration summary for the bundle.

    Each output key is named here. A field that is not named is not in the
    summary. A secret field gives only a ``<field>_set`` bool. Every URL goes
    through :func:`strip_url_userinfo`.
    """
    connect = config.connect
    wb = config.workbench
    git = wb.git_test
    k8s = wb.kubernetes
    pm = config.package_manager
    perf = config.performance
    runtimes = config.runtimes
    return {
        "deployment_name": config.deployment_name,
        "extension_dirs": list(config.extension_dirs),
        "connect": {
            "enabled": connect.enabled,
            "url": strip_url_userinfo(connect.url),
            "version": connect.version,
            "deploy_timeout": connect.deploy_timeout,
            "api_key_set": bool(connect.api_key),
        },
        "workbench": {
            "enabled": wb.enabled,
            "url": strip_url_userinfo(wb.url),
            "version": wb.version,
            "api_key_set": bool(wb.api_key),
            "session_profiles": wb.session_profiles,
            "session_count": wb.session_count,
            "job_timeout": wb.job_timeout,
            "test_packages": list(wb.test_packages),
            "idle_timeout_minutes": wb.idle_timeout_minutes,
            "idle_grace_seconds": wb.idle_grace_seconds,
            "extensions": {
                "vscode": list(wb.extensions.vscode),
                "positron": list(wb.extensions.positron),
                "jupyterlab": list(wb.extensions.jupyterlab),
            },
            "kubernetes": {
                "enabled": k8s.enabled,
                "namespace": k8s.namespace,
                "node_pool_profiles": dict(k8s.node_pool_profiles),
                "max_sessions": k8s.max_sessions,
                "profile_cpu_limit": dict(k8s.profile_cpu_limit),
                "profile_memory_limit_gib": dict(k8s.profile_memory_limit_gib),
            },
            "git_test": None
            if git is None
            else {
                "clone_url": strip_url_userinfo(git.clone_url),
                "auth_method": git.auth_method,
                "token_set": bool(git.token),
            },
            "chronicle_data_path": wb.chronicle_data_path,
        },
        "package_manager": {
            "enabled": pm.enabled,
            "url": strip_url_userinfo(pm.url),
            "version": pm.version,
            "token_set": bool(pm.token),
        },
        "auth": {
            "provider": config.auth.provider,
            "idp": config.auth.idp,
            "password_set": bool(config.auth.password),
        },
        "runtimes": {
            "r_versions": list(runtimes.r_versions),
            "python_versions": list(runtimes.python_versions),
            "r_excluded_versions": list(runtimes.r_excluded_versions),
            "python_excluded_versions": list(runtimes.python_excluded_versions),
        },
        "performance": {
            "page_load_timeout": perf.page_load_timeout,
            "download_timeout": perf.download_timeout,
            "p95_response_time": perf.p95_response_time,
            "avg_response_time": perf.avg_response_time,
            "concurrent_requests": perf.concurrent_requests,
            "disk_usage_max_pct": perf.disk_usage_max_pct,
            "memory_available_min_pct": perf.memory_available_min_pct,
            "load_user_counts": list(perf.load_user_counts),
            "load_max_connections": perf.load_max_connections,
            "load_success_rate_threshold": perf.load_success_rate_threshold,
            "load_test_tool": perf.load_test_tool,
            "load_test_duration": perf.load_test_duration,
            "load_test_spawn_rate": perf.load_test_spawn_rate,
        },
        "data_sources": [
            {
                "name": ds.name,
                "type": ds.type,
                "connection_string_set": bool(ds.connection_string),
            }
            for ds in config.data_sources
        ],
        "email_enabled": config.email_enabled,
        "monitoring_enabled": config.monitoring_enabled,
        "chronicle_enabled": config.chronicle_enabled,
        "security_policy_checks_enabled": config.security_policy_checks_enabled,
        "insecure": config.insecure,
        "ca_bundle": str(config.ca_bundle) if config.ca_bundle is not None else None,
        "cert_expiry_warning_days": config.cert_expiry_warning_days,
        "proxy": {
            "url": strip_url_userinfo(config.proxy.url),
            "no_proxy": list(config.proxy.no_proxy),
            "enabled": config.proxy.enabled,
            "trust_env": config.proxy.trust_env,
        },
    }
