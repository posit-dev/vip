"""Tests for outbound-proxy support (vip.proxy) and its wiring into clients.

Two layers:

1. Unit tests for ``vip.proxy`` — that ``build_proxy_map`` mirrors httpx's own
   ``get_environment_proxies`` (including NO_PROXY formatting and the
   ``NO_PROXY=*`` short-circuit), that ``proxy_for_url`` reproduces httpx's
   most-specific-pattern selection, and that ``playwright_proxy`` renders a
   correct Playwright dict.

2. An end-to-end test that a real ``BaseClient`` actually routes its request
   through a proxy. A logging CONNECT proxy is stood up on an ephemeral port;
   the test asserts the client's request produces a CONNECT line at the proxy
   (proving env-proxy resolution is no longer suppressed by the custom
   transport) and that a NO_PROXY host bypasses it. This is the regression test
   that prevents the "custom transport disables env proxies" bug from silently
   returning.
"""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest

from vip.proxy import (
    ProxyConfig,
    build_mounts,
    build_proxy_map,
    playwright_proxy,
    proxy_for_url,
    verify_with_env_ca,
)

# ---------------------------------------------------------------------------
# build_proxy_map — parity with httpx and resolution order
# ---------------------------------------------------------------------------


def test_env_map_matches_httpx(monkeypatch):
    """With no explicit config, build_proxy_map must equal httpx's own env map."""
    from httpx._utils import get_environment_proxies

    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv(var.lower(), raising=False)
    monkeypatch.setenv("http_proxy", "http://server:8080")
    monkeypatch.setenv("https_proxy", "http://server:8080")
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1,.internal.example,directhost.example")

    assert build_proxy_map(ProxyConfig()) == dict(get_environment_proxies())


def test_lowercase_and_uppercase_env_are_equivalent(monkeypatch):
    """The customer's lowercase http_proxy must resolve identically to uppercase."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("http_proxy", "http://server:8080")
    monkeypatch.setenv("https_proxy", "http://server:8080")
    lower = build_proxy_map(ProxyConfig())

    for var in ("http_proxy", "https_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://server:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://server:8080")
    upper = build_proxy_map(ProxyConfig())

    assert lower == upper == {"http://": "http://server:8080", "https://": "http://server:8080"}


def test_scheme_less_explicit_url_is_normalized(monkeypatch):
    """A bare host:port explicit proxy must default to http:// (like httpx env),
    so httpx.Proxy() doesn't raise "Unknown scheme for proxy URL"."""
    import httpx

    proxy_map = build_proxy_map(ProxyConfig(url="proxy.corp:8080"))
    assert proxy_map["all://"] == "http://proxy.corp:8080"
    # And it must actually build without raising.
    build_mounts(proxy_map)
    httpx.Proxy(proxy_map["all://"])  # would raise if scheme were missing


def test_no_proxy_applies_in_env_mode(monkeypatch):
    """config.no_proxy bypass hosts must merge into an env-derived map too,
    not only when an explicit url is set."""
    monkeypatch.setenv("HTTPS_PROXY", "http://server:8080")
    monkeypatch.delenv("NO_PROXY", raising=False)
    proxy_map = build_proxy_map(ProxyConfig(no_proxy=["directhost.example"]))
    assert proxy_map["all://*directhost.example"] is None
    assert proxy_for_url("https://directhost.example/x", proxy_map) is None
    assert proxy_for_url("https://other.example/x", proxy_map) == "http://server:8080"


def test_no_proxy_not_added_when_env_has_no_proxy(monkeypatch):
    """With no env proxy, config.no_proxy has nothing to bypass — map stays empty."""
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(var, raising=False)
    assert build_proxy_map(ProxyConfig(no_proxy=["directhost.example"])) == {}


def test_explicit_url_overrides_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://env-proxy:9999")
    cfg = ProxyConfig(url="http://explicit:8080", no_proxy=["localhost", ".internal.example"])
    proxy_map = build_proxy_map(cfg)
    assert proxy_map["all://"] == "http://explicit:8080"
    # env proxy must not leak in
    assert "http://env-proxy:9999" not in proxy_map.values()
    # NO_PROXY formatting mirrors httpx: bare-ish domain -> all://*<host>,
    # leading-dot domain -> all://*.<host>, localhost -> all://localhost.
    assert proxy_map["all://localhost"] is None
    assert proxy_map["all://*.internal.example"] is None


def test_disabled_forces_direct_even_with_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://server:8080")
    assert build_proxy_map(ProxyConfig(enabled=False)) == {}


def test_trust_env_false_ignores_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://server:8080")
    assert build_proxy_map(ProxyConfig(trust_env=False)) == {}


def test_no_proxy_star_short_circuits(monkeypatch):
    """NO_PROXY=* disables all proxying, matching httpx."""
    monkeypatch.setenv("HTTPS_PROXY", "http://server:8080")
    monkeypatch.setenv("NO_PROXY", "*")
    assert build_proxy_map(ProxyConfig()) == {}


def test_none_config_reads_env(monkeypatch):
    """Passing None (no ProxyConfig) reads the environment, like httpx's default."""
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://server:8080")
    monkeypatch.delenv("NO_PROXY", raising=False)
    assert build_proxy_map(None)["https://"] == "http://server:8080"


def test_no_proxy_as_comma_string_in_from_dict():
    cfg = ProxyConfig.from_dict({"url": "http://p:8080", "no_proxy": "localhost, .internal"})
    assert cfg.no_proxy == ["localhost", ".internal"]


# ---------------------------------------------------------------------------
# proxy_for_url — parity with httpx's own transport selection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://connect.example.com/x", "http://p:8080"),
        ("https://directhost.example/x", None),  # exact NO_PROXY host bypasses
        ("https://a.internal.example/x", None),  # subdomain of .internal.example bypasses
        ("http://localhost:9/x", None),
        ("https://127.0.0.1/x", None),
    ],
)
def test_proxy_for_url_matches_httpx(url, expected):
    cfg = ProxyConfig(
        url="http://p:8080",
        no_proxy=["localhost", "127.0.0.1", ".internal.example", "directhost.example"],
    )
    proxy_map = build_proxy_map(cfg)
    got = proxy_for_url(url, proxy_map)
    assert got == expected

    # Cross-check against httpx's own selection to guarantee parity.
    from httpx._utils import URLPattern

    target = httpx.URL(url)
    httpx_pick = None
    for pattern in sorted(URLPattern(k) for k in proxy_map):
        if pattern.matches(target):
            httpx_pick = proxy_map[pattern.pattern]
            break
    assert got == httpx_pick


def test_proxy_for_url_empty_map_is_direct():
    assert proxy_for_url("https://x/y", {}) is None


# ---------------------------------------------------------------------------
# build_mounts — keeps verify, composes with a base transport
# ---------------------------------------------------------------------------


def test_build_mounts_empty_map_is_empty():
    assert build_mounts({}) == {}


def test_build_mounts_selects_proxy_and_bypass():
    cfg = ProxyConfig(url="http://p:8080", no_proxy=["directhost.example"])
    proxy_map = build_proxy_map(cfg)
    mounts = build_mounts(proxy_map, verify=False)
    base = httpx.HTTPTransport(retries=3, verify=False)
    client = httpx.Client(transport=base, mounts=mounts)
    try:

        def chosen_proxy(url):
            t = client._transport_for_url(httpx.URL(url))
            pool = getattr(t, "_pool", None)
            return getattr(pool, "_proxy_url", None) if pool else None

        proxied = chosen_proxy("https://connect.example.com/x")
        assert proxied is not None and proxied.host == b"p"
        # NO_PROXY host must fall to a direct transport (no proxy on the pool).
        assert chosen_proxy("https://directhost.example/x") is None
    finally:
        client.close()


# ---------------------------------------------------------------------------
# playwright_proxy
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# verify_with_env_ca — keeps SSL_CERT_FILE honored despite trust_env=False
# ---------------------------------------------------------------------------


def test_verify_with_env_ca_passes_through_false_and_str():
    """insecure (False) and an explicit CA-bundle path are authoritative."""
    assert verify_with_env_ca(False) is False
    assert verify_with_env_ca("/etc/ssl/corp.pem") == "/etc/ssl/corp.pem"


def test_verify_with_env_ca_true_returns_context_honoring_env(monkeypatch, tmp_path):
    """verify=True must become an SSLContext that includes SSL_CERT_FILE certs,
    so pinning trust_env=False on the request does not drop a corporate CA."""
    import ssl
    import subprocess

    cert = tmp_path / "c.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(tmp_path / "k.pem"),
            "-out",
            str(cert),
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=corp",
        ],
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("SSL_CERT_FILE", str(cert))
    result = verify_with_env_ca(True)
    assert isinstance(result, ssl.SSLContext)
    # The single corp cert is loaded (vs the large certifi bundle when ignored).
    assert len(result.get_ca_certs()) == 1


def test_playwright_proxy_none_when_no_proxy():
    assert playwright_proxy({}) is None


def test_playwright_proxy_renders_server_and_bypass():
    cfg = ProxyConfig(url="http://p:8080", no_proxy=["localhost", ".internal.example"])
    pw = playwright_proxy(build_proxy_map(cfg))
    assert pw is not None
    assert pw["server"] == "http://p:8080"
    bypass = set(pw["bypass"].split(","))
    assert "localhost" in bypass
    assert ".internal.example" in bypass


def test_playwright_proxy_prefers_https_env(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://httpproxy:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://httpsproxy:2")
    monkeypatch.delenv("NO_PROXY", raising=False)
    pw = playwright_proxy(build_proxy_map(ProxyConfig()))
    assert pw is not None and pw["server"] == "http://httpsproxy:2"


# ---------------------------------------------------------------------------
# _launch_chromium passes the proxy dict through to Playwright
# ---------------------------------------------------------------------------


def test_launch_chromium_omits_proxy_when_none():
    from unittest.mock import MagicMock

    from vip.auth import _launch_chromium

    pw = MagicMock()
    _launch_chromium(pw, headless=True, proxy=None)
    assert pw.chromium.launch.call_args.kwargs == {"headless": True}


def test_launch_chromium_passes_proxy_dict():
    from unittest.mock import MagicMock

    from vip.auth import _launch_chromium

    pw = MagicMock()
    proxy = {"server": "http://p:8080", "bypass": "localhost"}
    _launch_chromium(pw, headless=False, proxy=proxy)
    kwargs = pw.chromium.launch.call_args.kwargs
    assert kwargs == {"headless": False, "proxy": proxy}


# ---------------------------------------------------------------------------
# End-to-end: BaseClient actually routes through a proxy (regression)
# ---------------------------------------------------------------------------


class _LoggingProxy:
    """A minimal CONNECT/absolute-URI proxy that records the first request line.

    It does not tunnel; it replies 502 so the client fails fast. The point is
    only to observe *that the client connected to the proxy at all*, and for
    which target host.
    """

    def __init__(self) -> None:
        self.hits: list[str] = []
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(50)
        self._srv.settimeout(0.25)
        self.port = self._srv.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            try:
                data = conn.recv(4096)
                if data:
                    self.hits.append(data.split(b"\r\n", 1)[0].decode("latin1", "replace"))
                conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            finally:
                conn.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._srv.close()


@pytest.fixture
def logging_proxy():
    proxy = _LoggingProxy()
    yield proxy
    proxy.close()


def test_base_client_routes_through_proxy(logging_proxy):
    """The regression: a custom-transport client must still use the proxy.

    Before the fix, BaseClient's custom transport made httpx drop all env-proxy
    mounts, so this request would have gone direct (and never touched the
    proxy). Now it must produce a CONNECT to the target host at the proxy.
    """
    from vip.clients.base import BaseClient

    cfg = ProxyConfig(url=logging_proxy.url)
    client = BaseClient("https://connect.example.invalid", proxy=cfg, timeout=5.0)
    try:
        with pytest.raises(httpx.HTTPError):
            client._client.get("/x")
    finally:
        client.close()

    time.sleep(0.2)
    assert any("connect.example.invalid:443" in line for line in logging_proxy.hits), (
        f"expected a CONNECT to the target via the proxy, got {logging_proxy.hits!r}"
    )


def test_base_client_no_proxy_host_bypasses(logging_proxy):
    """A NO_PROXY host must go direct even when a proxy is configured."""
    from vip.clients.base import BaseClient

    cfg = ProxyConfig(url=logging_proxy.url, no_proxy=["connect.example.invalid"])
    client = BaseClient("https://connect.example.invalid", proxy=cfg, timeout=3.0)
    try:
        with pytest.raises(httpx.HTTPError):
            client._client.get("/x")
    finally:
        client.close()

    time.sleep(0.2)
    # Direct path: DNS for the .invalid host fails, and the proxy is never hit.
    assert logging_proxy.hits == [], (
        f"NO_PROXY host must not touch the proxy, got {logging_proxy.hits!r}"
    )


def test_base_client_disabled_ignores_env_proxy(monkeypatch, logging_proxy):
    """enabled=False forces direct even when HTTPS_PROXY points at the proxy."""
    from vip.clients.base import BaseClient

    monkeypatch.setenv("HTTPS_PROXY", logging_proxy.url)
    client = BaseClient(
        "https://connect.example.invalid", proxy=ProxyConfig(enabled=False), timeout=3.0
    )
    try:
        with pytest.raises(httpx.HTTPError):
            client._client.get("/x")
    finally:
        client.close()

    time.sleep(0.2)
    assert logging_proxy.hits == []


def test_fetch_content_routes_through_proxy_and_pins_trust_env(monkeypatch):
    """ConnectClient.fetch_content's ad-hoc httpx.get must carry the resolved
    proxy AND trust_env=False, so a NO_PROXY/disabled config can't silently
    fall back to the ambient env proxy (parity with every other bare call)."""
    import httpx

    from vip.clients.connect import ConnectClient

    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["proxy"] = kwargs.get("proxy")
        captured["trust_env"] = kwargs.get("trust_env")
        return httpx.Response(200, text="ok")

    monkeypatch.setattr("vip.clients.connect.httpx.get", fake_get)

    client = ConnectClient(
        "https://connect.example.com",
        api_key="k",
        proxy=ProxyConfig(url="http://proxy:8080"),
    )
    try:
        client.fetch_content("https://connect.example.com/content/1/x.html")
    finally:
        client.close()

    assert captured["proxy"] == "http://proxy:8080"
    assert captured["trust_env"] is False


def test_fetch_content_bypass_host_goes_direct_not_env_proxy(monkeypatch):
    """A NO_PROXY host in fetch_content must resolve to proxy=None with
    trust_env=False, i.e. genuinely direct — not the ambient env proxy."""
    import httpx

    from vip.clients.connect import ConnectClient

    monkeypatch.setenv("HTTPS_PROXY", "http://ambient:9999")
    captured = {}

    def fake_get(url, **kwargs):
        captured["proxy"] = kwargs.get("proxy")
        captured["trust_env"] = kwargs.get("trust_env")
        return httpx.Response(200, text="ok")

    monkeypatch.setattr("vip.clients.connect.httpx.get", fake_get)

    client = ConnectClient(
        "https://connect.example.com",
        api_key="k",
        proxy=ProxyConfig(url="http://proxy:8080", no_proxy=["connect.example.com"]),
    )
    try:
        client.fetch_content("https://connect.example.com/content/1/x.html")
    finally:
        client.close()

    # Bypass host -> proxy_for_url returns None, and trust_env=False stops httpx
    # from re-reading HTTPS_PROXY=http://ambient:9999.
    assert captured["proxy"] is None
    assert captured["trust_env"] is False


def test_base_client_no_proxy_config_is_direct(logging_proxy, monkeypatch):
    """With no proxy config and no env, the client goes direct (unchanged behaviour)."""
    from vip.clients.base import BaseClient

    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(var, raising=False)
    client = BaseClient("https://connect.example.invalid", timeout=3.0)
    try:
        assert client.proxy_map == {}
        with pytest.raises(httpx.HTTPError):
            client._client.get("/x")
    finally:
        client.close()
    assert logging_proxy.hits == []
