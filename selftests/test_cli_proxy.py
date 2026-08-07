"""The --proxy / --no-proxy CLI flags must emit a correct [proxy] TOML section.

``vip verify`` with URL flags (no --config) synthesizes a temp vip.toml via
``_generate_temp_config``. These tests exercise that generator directly and load
the result back through ``load_config`` to confirm the flags round-trip into a
ProxyConfig with the intended semantics.
"""

from __future__ import annotations

import argparse

from vip.cli import _generate_temp_config
from vip.config import load_config
from vip.proxy import build_proxy_map


def _args(**overrides) -> argparse.Namespace:
    defaults = {
        "connect_url": "https://connect.example.com",
        "workbench_url": None,
        "package_manager_url": None,
        "connect_version": None,
        "workbench_version": None,
        "package_manager_version": None,
        "idp": None,
        "insecure": False,
        "ca_bundle": None,
        "proxy": None,
        "no_proxy": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_no_proxy_flags_omits_section():
    path = _generate_temp_config(_args())
    text = open(path).read()
    assert "[proxy]" not in text
    cfg = load_config(path)
    # Default: env-driven (trust_env True, no explicit url).
    assert cfg.proxy.url == ""
    assert cfg.proxy.enabled is True
    assert cfg.proxy.trust_env is True


def test_proxy_flag_sets_url():
    path = _generate_temp_config(_args(proxy="http://proxy.corp:8080"))
    cfg = load_config(path)
    assert cfg.proxy.url == "http://proxy.corp:8080"
    proxy_map = build_proxy_map(cfg.proxy)
    assert proxy_map["all://"] == "http://proxy.corp:8080"


def test_proxy_and_no_proxy_flags():
    path = _generate_temp_config(
        _args(proxy="http://p:8080", no_proxy="localhost,.internal.example")
    )
    cfg = load_config(path)
    assert cfg.proxy.url == "http://p:8080"
    assert cfg.proxy.no_proxy == ["localhost", ".internal.example"]
    proxy_map = build_proxy_map(cfg.proxy)
    assert proxy_map["all://localhost"] is None
    assert proxy_map["all://*.internal.example"] is None


def test_empty_no_proxy_disables_proxying():
    """--no-proxy '' with no --proxy means enabled=false (force direct)."""
    path = _generate_temp_config(_args(no_proxy=""))
    text = open(path).read()
    assert "[proxy]" in text
    assert "enabled = false" in text
    cfg = load_config(path)
    assert cfg.proxy.enabled is False
    assert build_proxy_map(cfg.proxy) == {}


def test_whitespace_only_no_proxy_disables_proxying():
    """--no-proxy '   ' (whitespace only) must disable proxying, same as ''."""
    path = _generate_temp_config(_args(no_proxy="   "))
    text = open(path).read()
    assert "enabled = false" in text
    cfg = load_config(path)
    assert cfg.proxy.enabled is False
    assert build_proxy_map(cfg.proxy) == {}


def test_no_proxy_without_proxy_still_lists_hosts():
    """--no-proxy with hosts but no --proxy records the bypass list (so it also
    applies to an ambient env proxy)."""
    path = _generate_temp_config(_args(no_proxy="localhost"))
    cfg = load_config(path)
    assert cfg.proxy.no_proxy == ["localhost"]
    # enabled stays true so an env proxy is still consulted for other hosts.
    assert cfg.proxy.enabled is True
