"""Regression tests for the proxy-aware scheme-downgrade fix in resolve_url_scheme.

The bug: ``resolve_url_scheme`` probes ``https://`` with a proxy-honoring
``httpx.get`` but decides whether to downgrade to ``http://`` using
``_tls_listener_present`` — a raw ``socket.create_connection`` that bypasses the
proxy. On a proxy-only host, a proxy failure (or a proxy-routed reachability
failure) plus a failing direct socket made VIP silently rewrite the URL to
plaintext ``http://`` and then send credentials in the clear.

The fix, verified here:

* an ``httpx.ProxyError`` NEVER downgrades (it says nothing about the origin);
* when a proxy applies to the URL, ANY transport failure does not downgrade
  (the raw-socket tiebreak is meaningless for a path that goes via the proxy);
* the original direct-path behaviour (downgrade when nothing answers, keep
  https on a TLS-trust problem) is preserved when no proxy is involved.

These use a throwaway ``ProductConfig`` marked ``url_scheme_inferred=True`` (the
only state in which a downgrade is even considered) and monkeypatch the network
boundary (``httpx.get`` and ``_tls_listener_present``) so no real sockets open.
"""

from __future__ import annotations

import httpx
import pytest

from vip import auth as auth_mod
from vip.auth import resolve_url_scheme
from vip.config import ProductConfig
from vip.proxy import ProxyConfig


def _inferred_pc(url: str = "https://connect.example.com") -> ProductConfig:
    pc = ProductConfig(url=url)
    # _normalize_url already set https + inferred flag for a scheme-less host,
    # but the test passes an explicit https:// for clarity, so force the flag.
    pc.url_scheme_inferred = True
    return pc


@pytest.fixture(autouse=True)
def _clear_scheme_cache():
    """resolve_url_scheme memoises per (url, tls, proxy); clear between tests."""
    auth_mod._scheme_resolution_cache.clear()
    yield
    auth_mod._scheme_resolution_cache.clear()


# Ambient proxy variables are cleared package-wide by the autouse
# ``_no_ambient_proxy`` fixture in selftests/conftest.py -- a module-local copy
# here would shadow it by name and drift out of sync with the shared list.


# ---------------------------------------------------------------------------
# Proxy failure must never downgrade
# ---------------------------------------------------------------------------


def test_proxy_error_does_not_downgrade(monkeypatch):
    """A ProxyError keeps https:// — a proxy hiccup is not evidence about TLS."""

    def boom(*a, **kw):
        raise httpx.ProxyError("proxy refused CONNECT")

    monkeypatch.setattr(auth_mod.httpx, "get", boom)
    # If the tiebreak were consulted it would (wrongly) drive a downgrade; make
    # it loud if it is ever called on this path.
    monkeypatch.setattr(
        auth_mod,
        "_tls_listener_present",
        lambda *a, **kw: pytest.fail("tiebreak must not run on a ProxyError"),
    )

    pc = _inferred_pc()
    resolved = resolve_url_scheme(pc, proxy=ProxyConfig(url="http://proxy:8080"))

    assert resolved == "https://connect.example.com"
    assert pc.url == "https://connect.example.com"


def test_proxy_error_warning_redacts_credentials(monkeypatch, capsys):
    """The proxy-failure warning must not print embedded user:pass credentials.

    resolve_url_scheme names the applicable proxy in its warning; an
    authenticated proxy (http://user:pass@host) must be redacted first so the
    password never reaches stdout/CI logs."""

    def boom(*a, **kw):
        raise httpx.ProxyError("proxy refused CONNECT")

    monkeypatch.setattr(auth_mod.httpx, "get", boom)
    monkeypatch.setattr(auth_mod, "_tls_listener_present", lambda *a, **kw: False)

    pc = _inferred_pc()
    resolve_url_scheme(pc, proxy=ProxyConfig(url="http://alice:s3cret@proxy.corp:8080"))

    out = capsys.readouterr().out
    assert "s3cret" not in out
    assert "alice" not in out
    # ...but the sanitized proxy host is still named for debugging.
    assert "proxy.corp:8080" in out


def test_transport_error_warning_redacts_credentials(monkeypatch, capsys):
    """The proxy-applies transport-error branch must redact credentials too."""

    def boom(*a, **kw):
        raise httpx.ConnectTimeout("timed out mid-tunnel")

    monkeypatch.setattr(auth_mod.httpx, "get", boom)

    pc = _inferred_pc()
    resolve_url_scheme(pc, proxy=ProxyConfig(url="http://alice:s3cret@proxy.corp:8080"))

    out = capsys.readouterr().out
    assert "s3cret" not in out
    assert "proxy.corp:8080" in out


def test_proxy_routed_transport_error_does_not_downgrade(monkeypatch):
    """With a proxy in effect, a non-ProxyError transport failure still must not
    downgrade — the raw-socket tiebreak bypasses the proxy and would mislead."""

    def boom(*a, **kw):
        raise httpx.ConnectTimeout("read timed out mid-tunnel")

    monkeypatch.setattr(auth_mod.httpx, "get", boom)
    # The direct socket "succeeds" (host reachable directly) — under the old
    # logic that would still not downgrade, but the important guarantee is the
    # proxy branch does not even consult it. Make it fail the test if called.
    monkeypatch.setattr(
        auth_mod,
        "_tls_listener_present",
        lambda *a, **kw: pytest.fail("tiebreak must not run while a proxy applies"),
    )

    pc = _inferred_pc()
    resolved = resolve_url_scheme(pc, proxy=ProxyConfig(url="http://proxy:8080"))

    assert resolved == "https://connect.example.com"


def test_env_proxy_also_guards_downgrade(monkeypatch):
    """The guard applies to an ambient env proxy too (the customer's case)."""
    monkeypatch.setenv("https_proxy", "http://server:8080")

    def boom(*a, **kw):
        raise httpx.ProxyError("bad gateway from proxy")

    monkeypatch.setattr(auth_mod.httpx, "get", boom)
    monkeypatch.setattr(
        auth_mod,
        "_tls_listener_present",
        lambda *a, **kw: pytest.fail("must not run"),
    )

    pc = _inferred_pc()
    # proxy=None => build_proxy_map reads the env, which points at the proxy.
    resolved = resolve_url_scheme(pc, proxy=None)
    assert resolved == "https://connect.example.com"


def test_no_proxy_host_still_uses_direct_tiebreak(monkeypatch):
    """A host in NO_PROXY takes the direct path, so the tiebreak still applies
    and a genuine no-listener case downgrades as before."""
    calls = {"get": 0, "tiebreak": 0}

    def boom(*a, **kw):
        calls["get"] += 1
        raise httpx.ConnectError("connection refused")

    def no_listener(*a, **kw):
        calls["tiebreak"] += 1
        return False

    monkeypatch.setattr(auth_mod.httpx, "get", boom)
    monkeypatch.setattr(auth_mod, "_tls_listener_present", no_listener)

    pc = _inferred_pc()
    cfg = ProxyConfig(url="http://proxy:8080", no_proxy=["connect.example.com"])
    resolved = resolve_url_scheme(pc, proxy=cfg)

    # No proxy applies to this host -> direct probe fails -> tiebreak says "no
    # listener" -> downgrade, exactly as without any proxy configured.
    assert calls["tiebreak"] == 1
    assert resolved == "http://connect.example.com"


# ---------------------------------------------------------------------------
# Original (no-proxy) behaviour is preserved
# ---------------------------------------------------------------------------


def test_no_proxy_no_listener_downgrades(monkeypatch):
    def boom(*a, **kw):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(auth_mod.httpx, "get", boom)
    monkeypatch.setattr(auth_mod, "_tls_listener_present", lambda *a, **kw: False)

    pc = _inferred_pc()
    assert resolve_url_scheme(pc) == "http://connect.example.com"


def test_no_proxy_tls_listener_keeps_https(monkeypatch):
    def boom(*a, **kw):
        raise httpx.ConnectError("cert verify failed")

    monkeypatch.setattr(auth_mod.httpx, "get", boom)
    monkeypatch.setattr(auth_mod, "_tls_listener_present", lambda *a, **kw: True)

    pc = _inferred_pc()
    assert resolve_url_scheme(pc) == "https://connect.example.com"


def test_successful_probe_keeps_https(monkeypatch):
    monkeypatch.setattr(auth_mod.httpx, "get", lambda *a, **kw: httpx.Response(200))
    pc = _inferred_pc()
    assert resolve_url_scheme(pc) == "https://connect.example.com"


def test_explicit_scheme_never_probes(monkeypatch):
    """An explicit scheme (url_scheme_inferred=False) must not touch the network."""

    def fail(*a, **kw):
        raise AssertionError("must not probe when the scheme was explicit")

    monkeypatch.setattr(auth_mod.httpx, "get", fail)
    pc = ProductConfig(url="https://connect.example.com")  # inferred=False
    assert resolve_url_scheme(pc, proxy=ProxyConfig(url="http://p:8080")) == (
        "https://connect.example.com"
    )


# ---------------------------------------------------------------------------
# The probe itself is routed through the proxy (trust_env pinned off)
# ---------------------------------------------------------------------------


def test_probe_is_sent_through_the_configured_proxy(monkeypatch):
    seen = {}

    def record(url, *args, **kwargs):
        seen["url"] = url
        seen["proxy"] = kwargs.get("proxy")
        seen["trust_env"] = kwargs.get("trust_env")
        return httpx.Response(200)

    monkeypatch.setattr(auth_mod.httpx, "get", record)

    pc = _inferred_pc()
    resolve_url_scheme(pc, proxy=ProxyConfig(url="http://proxy:8080"))

    assert seen["proxy"] == "http://proxy:8080"
    # trust_env must be pinned False so the resolved per-URL proxy is authoritative.
    assert seen["trust_env"] is False
