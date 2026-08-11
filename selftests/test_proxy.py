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

import httpx
import pytest

from vip.proxy import (
    ProxyConfig,
    build_mounts,
    build_proxy_map,
    chromium_launch_args,
    playwright_proxy,
    proxy_for_url,
    redact_proxy_url,
    verify_with_env_ca,
)

# ---------------------------------------------------------------------------
# build_proxy_map — parity with httpx and resolution order
# ---------------------------------------------------------------------------


def test_env_map_matches_httpx(monkeypatch):
    """With no explicit config, build_proxy_map matches httpx's own env map.

    Uses both http_proxy and https_proxy so the http->https promotion (see
    test_http_proxy_promoted_to_https) is a no-op here and parity is exact; the
    promotion is the one deliberate divergence and has its own test."""
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


def test_config_no_proxy_star_short_circuits_explicit_url():
    """A "*" in the config no_proxy list bypasses everything, like NO_PROXY=* —
    not a useless all://** pattern that leaves the explicit proxy still active."""
    assert build_proxy_map(ProxyConfig(url="http://p:8080", no_proxy=["*"])) == {}
    assert (
        proxy_for_url(
            "https://anything.example",
            build_proxy_map(ProxyConfig(url="http://p:8080", no_proxy=["*"])),
        )
        is None
    )


def test_config_no_proxy_star_short_circuits_env(monkeypatch):
    """ "*" in config no_proxy also bypasses an env-derived proxy."""
    monkeypatch.setenv("HTTPS_PROXY", "http://envp:8080")
    monkeypatch.delenv("NO_PROXY", raising=False)
    assert build_proxy_map(ProxyConfig(no_proxy=["*"])) == {}


def test_http_proxy_promoted_to_https(monkeypatch):
    """A lone HTTP_PROXY must also carry https (the org's single outbound tunnel):
    the org points only http_proxy at their gateway and expects https to tunnel
    through it via CONNECT. httpx alone would send https direct."""
    for var in ("HTTPS_PROXY", "ALL_PROXY", "https_proxy", "all_proxy", "NO_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://gw:3128")
    proxy_map = build_proxy_map(ProxyConfig())
    assert proxy_map == {"http://": "http://gw:3128", "https://": "http://gw:3128"}
    assert proxy_for_url("https://connect.example", proxy_map) == "http://gw:3128"


def test_explicit_https_proxy_not_overridden_by_http(monkeypatch):
    """An explicit HTTPS_PROXY is a deliberate choice — promotion must not clobber
    it, even when it differs from HTTP_PROXY."""
    for var in ("ALL_PROXY", "all_proxy", "NO_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://http-gw:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://https-gw:2")
    proxy_map = build_proxy_map(ProxyConfig())
    assert proxy_map["https://"] == "http://https-gw:2"
    assert proxy_for_url("https://connect.example", proxy_map) == "http://https-gw:2"


def test_all_proxy_not_promoted_over_http(monkeypatch):
    """ALL_PROXY already covers https, so an http_proxy alongside it must not add
    a redundant/conflicting https:// key."""
    for var in ("HTTPS_PROXY", "https_proxy", "NO_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://http-gw:1")
    monkeypatch.setenv("ALL_PROXY", "http://all-gw:2")
    proxy_map = build_proxy_map(ProxyConfig())
    assert "https://" not in proxy_map
    assert proxy_for_url("https://connect.example", proxy_map) == "http://all-gw:2"


def test_http_proxy_promotion_still_honors_no_proxy(monkeypatch):
    """A NO_PROXY host must still bypass a promoted http->https map."""
    for var in ("HTTPS_PROXY", "ALL_PROXY", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://gw:3128")
    monkeypatch.setenv("NO_PROXY", ".internal.example")
    proxy_map = build_proxy_map(ProxyConfig())
    assert proxy_for_url("https://x.internal.example", proxy_map) is None
    assert proxy_for_url("https://connect.example", proxy_map) == "http://gw:3128"


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


def test_from_dict_rejects_non_boolean_enabled():
    """A quoted "false" would be truthy and silently turn proxying ON — reject it."""
    with pytest.raises(ValueError, match="enabled must be a boolean"):
        ProxyConfig.from_dict({"enabled": "false"})


def test_from_dict_rejects_non_boolean_trust_env():
    with pytest.raises(ValueError, match="trust_env must be a boolean"):
        ProxyConfig.from_dict({"trust_env": "no"})


def test_from_dict_accepts_real_booleans():
    cfg = ProxyConfig.from_dict({"enabled": False, "trust_env": False})
    assert cfg.enabled is False
    assert cfg.trust_env is False


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
# verify_with_env_ca — keeps SSL_CERT_FILE honored despite trust_env=False
# ---------------------------------------------------------------------------


def test_verify_with_env_ca_passes_through_false_and_str():
    """insecure (False) and an explicit CA-bundle path are authoritative."""
    assert verify_with_env_ca(False) is False
    assert verify_with_env_ca("/etc/ssl/corp.pem") == "/etc/ssl/corp.pem"


def test_verify_with_env_ca_true_returns_context_honoring_env(monkeypatch):
    """verify=True must become an SSLContext that includes SSL_CERT_FILE certs,
    so pinning trust_env=False on the request does not drop a corporate CA.

    Uses a checked-in single-cert PEM fixture (selftests/fixtures/corp_ca.pem)
    rather than shelling out to openssl — the assertion only needs one
    recognisable CA in the store, and a fixture keeps this a pure-unit test with
    no external-tool dependency."""
    import ssl
    from pathlib import Path

    cert = Path(__file__).parent / "fixtures" / "corp_ca.pem"
    monkeypatch.setenv("SSL_CERT_FILE", str(cert))
    result = verify_with_env_ca(True)
    assert isinstance(result, ssl.SSLContext)
    # The single corp cert is loaded (vs the large certifi bundle when ignored).
    assert len(result.get_ca_certs()) == 1


# ---------------------------------------------------------------------------
# playwright_proxy
# ---------------------------------------------------------------------------


def test_playwright_proxy_none_when_no_proxy():
    assert playwright_proxy({}) is None


def test_playwright_proxy_renders_server_and_bypass():
    cfg = ProxyConfig(url="http://p:8080", no_proxy=["localhost", ".internal.example"])
    pw = playwright_proxy(build_proxy_map(cfg))
    assert pw is not None
    assert pw["server"] == "http://p:8080"
    bypass = set(pw["bypass"].split(","))
    assert "localhost" in bypass
    # The httpx pattern's leading ``*`` is preserved so Chromium matches the same
    # hosts -- see test_bare_no_proxy_host_bypasses_subdomains_in_the_browser_too.
    assert "*.internal.example" in bypass


def test_bare_no_proxy_host_bypasses_subdomains_in_the_browser_too():
    """A bare NO_PROXY host must bypass the apex and its subdomains for Chromium.

    httpx renders ``NO_PROXY=example.com`` as ``all://*example.com``, whose
    regex is ``^(.+\\.)?example\\.com$`` -- the apex plus dot-separated
    subdomains. Chromium reads a bare ``example.com`` as an exact-host match, so
    rendering it that way makes the browser proxy the very subdomains every
    httpx path reaches directly, and products live on subdomains.

    Chromium has no single pattern with httpx's match set, so this takes two
    entries: the apex verbatim, plus ``*.example.com`` for subdomains.
    """
    cfg = ProxyConfig(url="http://p:8080", no_proxy=["example.com"])
    proxy_map = build_proxy_map(cfg)
    # httpx bypasses the apex and the subdomain ...
    assert proxy_for_url("https://example.com", proxy_map) is None
    assert proxy_for_url("https://connect.example.com", proxy_map) is None
    # ... so the browser must be told to as well.
    pw = playwright_proxy(proxy_map)
    assert pw is not None
    assert pw["bypass"] == "example.com,*.example.com"


@pytest.mark.parametrize("no_proxy_host", ["*.foo.com", ".*.foo.com", "**.foo.com", "*foo.com"])
def test_star_in_no_proxy_host_bypasses_nothing_in_the_browser_either(no_proxy_host):
    """A ``*`` inside a NO_PROXY host makes httpx's pattern unmatchable -- and the
    browser must be just as unmatchable.

    httpx builds its regex from the host verbatim, escaping it, so
    ``NO_PROXY=*.foo.com`` becomes ``all://**.foo.com`` with regex
    ``^(.+\\.)?\\*\\.foo\\.com$`` -- it requires a literal ``*`` in the hostname
    and therefore never matches anything real. Chromium's grammar *does* treat
    ``*`` as a glob, so rendering the entry naively hands the browser a working
    wildcard while every httpx call is proxied: on a mandated-proxy network the
    browser silently escapes the proxy.

    Users write this form often even though NO_PROXY has no wildcard syntax, so
    the safe reading is httpx's: it matches nothing, and so must the browser.
    """
    proxy_map = build_proxy_map(ProxyConfig(url="http://p:8080", no_proxy=[no_proxy_host]))
    # httpx proxies the subdomain -- the pattern cannot match it.
    assert proxy_for_url("https://wb.foo.com", proxy_map) == "http://p:8080"
    pw = playwright_proxy(proxy_map, "https://wb.foo.com")
    assert pw is not None
    assert "bypass" not in pw, f"unmatchable pattern leaked a browser bypass: {pw.get('bypass')!r}"


def test_bare_no_proxy_host_does_not_bypass_prefix_lookalikes():
    """The subdomain fix must not widen the bypass to suffix lookalikes.

    httpx is explicit that ``NO_PROXY=google.com`` disables ``google.com`` and
    ``www.google.com`` "but not wwwgoogle.com" -- its regex requires a dot
    separator. A single Chromium ``*example.com`` entry is a plain glob and does
    match ``badexample.com``, which would send browser traffic direct that every
    httpx path proxies: the same browser/API split in the opposite direction,
    and a wider hole than the one it closes.

    Verified against real Chromium: with ``bypass='*testdom.local'`` the browser
    reached ``badtestdom.local`` directly while httpx proxied it; with
    ``bypass='testdom.local,*.testdom.local'`` both proxied it.
    """
    cfg = ProxyConfig(url="http://p:8080", no_proxy=["example.com"])
    proxy_map = build_proxy_map(cfg)
    # httpx sends the lookalike through the proxy ...
    assert proxy_for_url("https://badexample.com", proxy_map) == "http://p:8080"
    # ... so the browser must not carry a glob that would bypass it.
    entries = playwright_proxy(proxy_map)["bypass"].split(",")
    assert "*example.com" not in entries
    assert entries == ["example.com", "*.example.com"]


def test_scheme_qualified_no_proxy_keeps_its_scheme_in_the_browser():
    """A NO_PROXY entry carrying a scheme bypasses that scheme only -- in the
    browser too.

    httpx keeps a ``"://"``-bearing NO_PROXY host as the pattern verbatim, so
    ``https://example.com`` bypasses https and still proxies http to the same
    host. Chromium's bypass grammar is
    ``[ SCHEME "://" ] HOSTNAME_PATTERN [ ":" PORT ]``, so dropping the scheme
    yields a scheme-less entry that bypasses *both* -- the browser goes direct
    where every httpx path proxies, which is the wider of the two failure
    directions and the one ``_bypass_host_for_url`` is already scheme-qualified
    to avoid.
    """
    proxy_map = build_proxy_map(ProxyConfig(url="http://p:8080", no_proxy=["https://example.com"]))
    assert "https://example.com" in proxy_map
    # httpx bypasses https to the apex, and proxies http to it ...
    assert proxy_for_url("https://example.com", proxy_map) is None
    assert proxy_for_url("http://example.com", proxy_map) == "http://p:8080"
    # ... plus subdomains on either scheme (the pattern is exact-host).
    assert proxy_for_url("https://wb.example.com", proxy_map) == "http://p:8080"
    # ... so the browser entry has to carry the scheme.
    pw = playwright_proxy(proxy_map)
    assert pw is not None
    assert pw["bypass"].split(",") == ["https://example.com"]


@pytest.mark.parametrize(
    "no_proxy_host,bypass",
    [
        # Wildcard host forms are matchable, and mean the same thing they mean
        # under ``all://`` -- just restricted to the one scheme.
        ("https://*example.com", "https://example.com,https://*.example.com"),
        ("https://*.example.com", "https://*.example.com"),
        # A leading dot is NOT a wildcard to httpx: URLPattern only special-cases
        # a host starting with ``*``, so ``.example.com`` compiles to the exact
        # regex ``^\.example\.com$``, which no real hostname matches. Chromium
        # *does* read a leading dot as a suffix match, so emitting the entry would
        # bypass every subdomain in the browser while httpx proxies them all.
        ("https://.example.com", None),
    ],
)
def test_scheme_qualified_no_proxy_wildcard_forms_match_httpx(no_proxy_host, bypass):
    """The scheme-qualified forms follow httpx's host handling, not Chromium's."""
    proxy_map = build_proxy_map(ProxyConfig(url="http://p:8080", no_proxy=[no_proxy_host]))
    pw = playwright_proxy(proxy_map, "https://wb.example.com")
    assert pw is not None
    if bypass is None:
        assert proxy_for_url("https://wb.example.com", proxy_map) == "http://p:8080"
        assert proxy_for_url("https://example.com", proxy_map) == "http://p:8080"
        assert "bypass" not in pw, (
            f"unmatchable pattern leaked a browser bypass: {pw.get('bypass')!r}"
        )
    else:
        assert pw["bypass"] == bypass


@pytest.mark.parametrize(
    "no_proxy_host,bypass,direct_scheme",
    [
        ("https://*", "https://*", "https"),
        ("http://*", "http://*", "http"),
    ],
)
def test_scheme_wide_no_proxy_wildcard_bypasses_that_scheme_in_the_browser(
    no_proxy_host, bypass, direct_scheme
):
    """``no_proxy = ["https://*"]`` means "bypass the proxy for all https".

    ``URLPattern("https://*")`` keeps ``host == ""`` (it normalises the ``*``
    away), so it matches every host on that scheme and httpx sends all https
    direct while still proxying http. Chromium spells the same thing the same
    way -- verified with a recording gateway: ``bypass='https://*'`` sends https
    direct and still routes http through the proxy.

    Rendering it as nothing leaves the browser proxying every https request that
    every httpx path sends direct. That is the too-narrow direction, so it does
    not escape a mandated proxy, but it still breaks the browser login against a
    proxy the operator has told VIP to avoid for https.
    """
    proxy_map = build_proxy_map(ProxyConfig(url="http://p:8080", no_proxy=[no_proxy_host]))
    proxied_scheme = "http" if direct_scheme == "https" else "https"
    assert proxy_for_url(f"{direct_scheme}://example.com", proxy_map) is None
    assert proxy_for_url(f"{proxied_scheme}://example.com", proxy_map) == "http://p:8080"
    pw = playwright_proxy(proxy_map, f"{direct_scheme}://example.com")
    assert pw is not None
    assert pw["bypass"] == bypass


def test_scheme_less_no_proxy_wildcard_emits_nothing_because_httpx_proxies_it():
    """``all://*`` must NOT render to a browser ``*``, even though it looks like
    "bypass everything".

    ``URLPattern("all://*")`` normalises to empty scheme *and* empty host, giving
    it the identical ``priority`` tuple to the catch-all ``all://`` that carries
    the proxy. Sorting is stable and ``all://`` is inserted first, so it wins and
    httpx **proxies** these requests -- both here and inside
    ``httpx.Client(mounts=...)``, which sorts the same keys the same way.

    A bare ``*`` is a working Chromium bypass (verified: both schemes go direct),
    so emitting one would bypass everything in the browser while every httpx path
    is proxied: the too-wide direction, silently escaping a mandated proxy. Only a
    scheme narrows the wildcard enough to be renderable. (``NO_PROXY=*`` -- the
    form operators actually write -- is short-circuited to an empty map by
    ``build_proxy_map`` long before this, and ``chromium_launch_args`` adds
    ``--no-proxy-server``.)
    """
    proxy_map = build_proxy_map(ProxyConfig(url="http://p:8080", no_proxy=["all://*"]))
    assert proxy_for_url("https://example.com", proxy_map) == "http://p:8080"
    assert proxy_for_url("http://example.com", proxy_map) == "http://p:8080"
    pw = playwright_proxy(proxy_map, "https://example.com")
    assert pw is not None
    assert "bypass" not in pw, f"scheme-less wildcard leaked a browser bypass: {pw.get('bypass')!r}"


@pytest.mark.parametrize(
    "no_proxy_host,bypass,direct,proxied",
    [
        # httpx normalises a scheme's DEFAULT port away at URL-parse time, so
        # ``https://*:443`` keeps port None and matches every https URL on ANY
        # port. Forwarding the literal :443 would restrict Chromium to 443.
        (
            "https://*:443",
            "https://*",
            ["https://ex.com", "https://ex.com:8443"],
            ["http://ex.com", "http://ex.com:8080"],
        ),
        ("http://*:80", "http://*", ["http://ex.com", "http://ex.com:8080"], ["https://ex.com"]),
        # A non-default port survives normalisation, so it must survive rendering.
        ("https://*:8443", "https://*:8443", ["https://ex.com:8443"], ["https://ex.com"]),
        (
            "all://*:8443",
            "*:8443",
            ["https://ex.com:8443", "http://ex.com:8443"],
            ["http://ex.com"],
        ),
        # The sharp one: ``all://`` has no default port, so :443 survives, and
        # httpx then matches only the scheme for which 443 is *not* the default --
        # http. A scheme-less Chromium ``:443`` also matches implicit-port https,
        # bypassing in the browser what every httpx path proxies. Qualify with the
        # other scheme to close that.
        (
            "all://*:443",
            "http://*:443",
            ["http://ex.com:443"],
            ["https://ex.com", "https://ex.com:443", "http://ex.com"],
        ),
        (
            "all://*:80",
            "https://*:80",
            ["https://ex.com:80"],
            ["http://ex.com", "http://ex.com:80"],
        ),
        # The same two rules on a real host rather than a wildcard.
        (
            "https://ex.com:443",
            "https://ex.com",
            ["https://ex.com", "https://ex.com:8443"],
            ["http://ex.com"],
        ),
        (
            "ex.com:443",
            "http://ex.com:443,http://*.ex.com:443",
            ["http://ex.com:443"],
            ["https://ex.com", "https://ex.com:443", "http://ex.com"],
        ),
        # Regression control: a non-default port on a bare host is unchanged.
        (
            "ex.com:8080",
            "ex.com:8080,*.ex.com:8080",
            ["https://ex.com:8080", "http://ex.com:8080"],
            ["https://ex.com"],
        ),
    ],
)
def test_playwright_bypass_matches_httpx_for_ports(no_proxy_host, bypass, direct, proxied):
    """Port handling must come from httpx's normalisation, not the pattern string.

    ``URLPattern`` resolves a port against the pattern's scheme (a default port
    becomes ``None``, i.e. "any port"), while Chromium compares against the
    request's effective port. Hand-parsing the pattern text diverges in both
    directions, so the port is taken from ``URLPattern`` and, for the one case
    where the two models genuinely disagree, the entry is scheme-qualified.
    """
    proxy_map = build_proxy_map(ProxyConfig(url="http://p:8080", no_proxy=[no_proxy_host]))
    for url in direct:
        assert proxy_for_url(url, proxy_map) is None, f"httpx should bypass {url}"
    for url in proxied:
        assert proxy_for_url(url, proxy_map) == "http://p:8080", f"httpx should proxy {url}"
    pw = playwright_proxy(proxy_map)
    assert pw is not None
    assert pw.get("bypass") == bypass


@pytest.mark.parametrize(
    "no_proxy_host,pattern,bypass,direct,proxied",
    [
        (
            "example.com",
            "all://*example.com",
            "example.com,*.example.com",
            ["example.com", "connect.example.com", "a.b.example.com"],
            ["badexample.com", "example.com.evil.test"],
        ),
        (
            ".internal.example",
            "all://*.internal.example",
            "*.internal.example",
            ["wb.internal.example"],
            ["internal.example", "badinternal.example"],
        ),
        (
            "localhost",
            "all://localhost",
            "localhost",
            ["localhost"],
            ["notlocalhost"],
        ),
        # httpx's URLPattern parses the mask as a URL *path* and drops it, so its
        # host regex is ^10\.0\.0\.0$ -- only the literal address bypasses, never
        # the range. Chromium would read 10.0.0.0/8 as a real CIDR rule and
        # bypass every host in it, sending internal traffic direct that every
        # httpx call proxies. Parity with httpx is the contract, so the mask is
        # dropped here too.
        (
            "10.0.0.0/8",
            "all://10.0.0.0/8",
            "10.0.0.0",
            ["10.0.0.0"],
            ["10.1.2.3", "10.0.0.1"],
        ),
        # Chromium's bypass grammar needs IPv6 literals bracketed; the bare form
        # is parsed with ':' as a port separator and never matches.
        (
            "::1",
            "all://[::1]",
            "[::1]",
            ["[::1]"],
            [],
        ),
    ],
)
def test_playwright_bypass_matches_httpx_for_each_no_proxy_form(
    no_proxy_host, pattern, bypass, direct, proxied
):
    """Every bypass pattern httpx builds must render to Playwright entries with
    the same match set -- asserted in *both* directions.

    The negative half is the point: a rendering that is merely "wide enough" to
    cover the subdomains also silently bypasses lookalikes httpx proxies, which
    is the same browser/API split pointing the other way.
    """
    proxy_map = build_proxy_map(ProxyConfig(url="http://p:8080", no_proxy=[no_proxy_host]))
    assert pattern in proxy_map
    for host in direct:
        assert proxy_for_url(f"https://{host}", proxy_map) is None, f"httpx should bypass {host}"
    for host in proxied:
        assert proxy_for_url(f"https://{host}", proxy_map) == "http://p:8080", (
            f"httpx should proxy {host}"
        )
    pw = playwright_proxy(proxy_map)
    assert pw is not None
    assert pw["bypass"] == bypass


def test_playwright_proxy_uses_the_http_proxy_for_an_http_target(monkeypatch):
    """With distinct per-scheme env proxies and an http:// target, the browser must
    get the same proxy httpx picks.

    Selecting on the https key regardless of the target hands Chromium the https
    proxy while every httpx path uses the http one -- a browser/API split that
    bites whenever a product is served over plain http (TLS terminated upstream,
    or after resolve_url_scheme downgrades an inferred https URL).
    """
    for var in ("ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://http-gw:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://https-gw:2")
    proxy_map = build_proxy_map(ProxyConfig())

    target = "http://wb.internal"
    httpx_pick = proxy_for_url(target, proxy_map)
    browser_pick = (playwright_proxy(proxy_map, target) or {}).get("server")

    assert httpx_pick == "http://http-gw:1"
    assert browser_pick == httpx_pick


def test_playwright_proxy_uses_the_https_proxy_for_an_https_target(monkeypatch):
    """The mirror case: an https target still selects the https proxy."""
    for var in ("ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://http-gw:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://https-gw:2")
    proxy_map = build_proxy_map(ProxyConfig())

    target = "https://connect.internal"
    assert (playwright_proxy(proxy_map, target) or {}).get("server") == proxy_for_url(
        target, proxy_map
    )


def test_playwright_proxy_keeps_the_server_when_the_target_is_bypassed():
    """A bypassed target must still leave a proxy server configured.

    The target URL selects *which* proxy, not whether there is one: the login
    browser does not stay on one host -- it follows a redirect to the IdP, which
    is not on the bypass list and does need the proxy. Chromium applies the
    bypass list per-request, so the target still goes direct.
    """
    cfg = ProxyConfig(url="http://p:8080", no_proxy=["internal.example"])
    proxy_map = build_proxy_map(cfg)
    target = "https://wb.internal.example"
    assert proxy_for_url(target, proxy_map) is None  # httpx reaches it directly
    pw = playwright_proxy(proxy_map, target)
    assert pw is not None
    assert pw["server"] == "http://p:8080"  # still available for the IdP hop
    # and the target is bypassed (apex + subdomains, matching httpx)
    assert pw["bypass"] == "internal.example,*.internal.example"


def test_playwright_proxy_falls_back_when_the_target_scheme_has_no_proxy(monkeypatch):
    """A target whose scheme has no key must still get the map's other proxy.

    ``target_url`` chooses *which* proxy, never *whether* there is one. With only
    HTTPS_PROXY set and an http:// product, returning None launches the browser
    with no proxy at all -- but the login immediately redirects to the https IdP,
    which every httpx path proxies. The browser would be the only thing on the
    box that cannot reach it.
    """
    for var in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy", "NO_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://gw:3128")
    proxy_map = build_proxy_map(ProxyConfig())
    assert proxy_map == {"https://": "http://gw:3128"}

    pw = playwright_proxy(proxy_map, "http://wb.internal")
    assert pw is not None, "browser must keep a proxy for the https IdP hop"
    assert pw["server"] == "http://gw:3128"
    # And that is the proxy httpx uses for the hop the browser actually needs it for.
    assert pw["server"] == proxy_for_url("https://idp.okta.com", proxy_map)
    # But the target itself must still be reached directly, exactly as httpx does,
    # or Chromium sends a plain-http request to a gateway that will 403/407 it.
    assert proxy_for_url("http://wb.internal", proxy_map) is None
    # Scheme-qualified: httpx only sends *http* to this host directly, and still
    # proxies https to the same host. A bare ``wb.internal`` is scheme-less in
    # Chromium's grammar and would bypass both, so an http product that redirects
    # to https on the same host would escape the proxy in the browser only.
    assert "http://wb.internal" in pw["bypass"].split(",")
    assert "wb.internal" not in pw["bypass"].split(",")
    assert proxy_for_url("https://wb.internal", proxy_map) == "http://gw:3128"


def test_fallback_target_bypass_is_scheme_qualified_for_ipv6_too(monkeypatch):
    """The scheme-qualified fallback entry still brackets an IPv6 literal.

    Chromium's bypass grammar reads a bare ``2001:db8::5`` as host + port, so an
    unbracketed entry silently never matches and the browser proxies a target
    httpx reaches directly. The map must leave the target's scheme uncovered --
    an ``all://`` from an explicit ``url`` would proxy it, so no fallback entry
    is added and the bracketing is never exercised.
    """
    for var in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy", "NO_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://gw:3128")
    m = build_proxy_map(ProxyConfig())
    assert proxy_for_url("http://[2001:db8::5]", m) is None, "fallback branch must be reachable"
    assert "http://[2001:db8::5]" in playwright_proxy(m, "http://[2001:db8::5]")["bypass"].split(
        ","
    )


def test_bypassed_target_is_not_added_twice_or_when_already_proxied():
    """The target only joins the bypass list when httpx would reach it directly."""
    # Proxied target (all:// covers it): no bypass entry for it.
    m = build_proxy_map(ProxyConfig(url="http://p:8080"))
    assert proxy_for_url("http://localhost:3939", m) == "http://p:8080"
    assert "bypass" not in playwright_proxy(m, "http://localhost:3939")
    # Already-bypassed target: the NO_PROXY pattern covers it; no duplicate.
    m2 = build_proxy_map(ProxyConfig(url="http://p:8080", no_proxy=["wb.internal"]))
    entries = playwright_proxy(m2, "https://wb.internal")["bypass"].split(",")
    assert entries.count("wb.internal") == 1
    # A target covered by a *wildcard* pattern must not be re-listed either --
    # proxy_for_url returns None for "a bypass matched" and for "nothing
    # matched", and only the latter needs an explicit entry.
    m3 = build_proxy_map(ProxyConfig(url="http://p:8080", no_proxy=[".internal.example"]))
    assert playwright_proxy(m3, "https://wb.internal.example")["bypass"] == "*.internal.example"


def test_bypassed_ipv6_target_is_bracketed_for_chromium():
    """An IPv6 target added to the bypass list needs Chromium's bracketed form."""
    m = build_proxy_map(ProxyConfig(url="http://p:8080", no_proxy=["2001:db8::1"]))
    pw = playwright_proxy(m, "http://[2001:db8::1]:8787")
    assert "[2001:db8::1]" in pw["bypass"].split(",")


def test_playwright_proxy_is_none_only_when_the_map_has_no_proxy_at_all():
    """The one case that legitimately launches Chromium unproxied."""
    assert playwright_proxy({}, "http://wb.internal") is None


def test_disabled_proxy_forces_the_browser_direct(monkeypatch):
    """``enabled = false`` / ``--no-proxy ''`` must reach Chromium, not just httpx.

    Omitting Playwright's ``proxy=`` does not mean "go direct" -- it means "decide
    for yourself", and Chromium then reads the ambient proxy environment (on
    Linux) or the system proxy settings. So the one case where the user has
    explicitly demanded a direct path is the case where the browser would proxy
    while every httpx call goes direct: precisely the split this module exists to
    remove. ``--no-proxy-server`` is the switch that actually forces it; note
    that Playwright rewrites a ``direct://`` server string into a real proxy
    (``normalizeProxySettings``), so that is not an option.
    """
    from vip.proxy import chromium_launch_args

    monkeypatch.setenv("HTTPS_PROXY", "http://gw:3128")
    assert chromium_launch_args(ProxyConfig(enabled=False)) == ["--no-proxy-server"]
    assert chromium_launch_args(ProxyConfig(trust_env=False)) == ["--no-proxy-server"]


def test_no_extra_launch_args_when_a_proxy_is_configured(monkeypatch):
    """A configured proxy is carried by ``proxy=``; --no-proxy-server would fight it."""
    from vip.proxy import chromium_launch_args

    monkeypatch.setenv("HTTPS_PROXY", "http://gw:3128")
    assert chromium_launch_args(ProxyConfig()) == []
    assert chromium_launch_args(ProxyConfig(url="http://p:8080")) == []


@pytest.mark.parametrize(
    "cfg",
    [
        ProxyConfig(url="http://p:8080", no_proxy=["*"]),
        ProxyConfig(no_proxy=["*"]),
        ProxyConfig(enabled=False),
        ProxyConfig(trust_env=False),
    ],
    ids=["url+star", "star-only", "disabled", "no-trust-env"],
)
def test_every_explicit_direct_request_reaches_chromium(cfg, monkeypatch):
    """Whenever the config explicitly routes everything direct, the browser must
    be told so too.

    ``build_proxy_map`` short-circuits a ``"*"`` in no_proxy to an empty map, the
    same as ``enabled = false`` -- but an empty map only means ``playwright_proxy``
    returns None, which leaves Chromium free to read the ambient environment or
    system proxy settings. So the user asks for "bypass everything" and gets httpx
    direct with the browser still proxied.
    """
    monkeypatch.setenv("HTTPS_PROXY", "http://ambient-gw:3128")
    assert build_proxy_map(cfg) == {}
    assert chromium_launch_args(cfg) == ["--no-proxy-server"]


def test_no_extra_launch_args_when_nothing_is_configured(monkeypatch):
    """Nothing configured is not the same as explicitly off -- leave Chromium alone,
    exactly as before this module existed."""
    from vip.proxy import chromium_launch_args

    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(var, raising=False)
    assert chromium_launch_args(ProxyConfig()) == []
    assert chromium_launch_args(None) == []


def test_playwright_proxy_without_target_keeps_https_first_selection(monkeypatch):
    """Callers with no single navigation target keep the https-first behavior."""
    for var in ("ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://http-gw:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://https-gw:2")
    pw = playwright_proxy(build_proxy_map(ProxyConfig()))
    assert pw is not None and pw["server"] == "http://https-gw:2"


def test_playwright_proxy_prefers_https_env(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://httpproxy:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://httpsproxy:2")
    monkeypatch.delenv("NO_PROXY", raising=False)
    pw = playwright_proxy(build_proxy_map(ProxyConfig()))
    assert pw is not None and pw["server"] == "http://httpsproxy:2"


def test_playwright_proxy_splits_authenticated_credentials():
    """An authenticated proxy must expose its creds in Playwright's dedicated
    username/password fields, NOT embedded in ``server`` — Chromium ignores
    userinfo in the server string, so leaving it there 407s the browser login
    while every httpx path (which parses the userinfo) authenticates fine. The
    ``server`` handed to Playwright must also be credential-free so the password
    can't leak into browser logs."""
    cfg = ProxyConfig(url="http://alice:s3cret@proxy.corp:8080")
    pw = playwright_proxy(build_proxy_map(cfg))
    assert pw is not None
    assert pw["username"] == "alice"
    assert pw["password"] == "s3cret"
    assert pw["server"] == "http://proxy.corp:8080"
    assert "s3cret" not in pw["server"]


def test_playwright_proxy_no_credential_keys_when_unauthenticated():
    """A proxy with no userinfo must not sprout empty username/password keys —
    Playwright would try to authenticate with a blank user and could 407."""
    pw = playwright_proxy(build_proxy_map(ProxyConfig(url="http://proxy.corp:8080")))
    assert pw is not None
    assert pw["server"] == "http://proxy.corp:8080"
    assert "username" not in pw
    assert "password" not in pw


def test_http_only_env_browser_and_httpx_agree_via_tunnel(monkeypatch):
    """With only HTTP_PROXY set (the "single outbound tunnel" org), https must
    tunnel through that proxy on BOTH the httpx and browser paths, and they must
    agree — no browser-vs-API split, and no https-goes-direct dead end on a
    proxy-only network. Guards both the http->https promotion and the
    _primary_proxy_server selection staying in lockstep with proxy_for_url."""
    for var in ("HTTPS_PROXY", "ALL_PROXY", "https_proxy", "all_proxy", "NO_PROXY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://corp-proxy:3128")
    proxy_map = build_proxy_map(ProxyConfig())
    httpx_pick = proxy_for_url("https://connect.example", proxy_map)
    browser_pick = (playwright_proxy(proxy_map) or {}).get("server")
    assert httpx_pick == "http://corp-proxy:3128"
    assert browser_pick == "http://corp-proxy:3128"
    assert httpx_pick == browser_pick


# ---------------------------------------------------------------------------
# redact_proxy_url — never leak proxy credentials into logs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://alice:s3cret@proxy.corp:8080", "http://proxy.corp:8080"),
        ("http://alice:s3cret@proxy.corp", "http://proxy.corp"),
        ("https://user:pw@10.0.0.1:3128", "https://10.0.0.1:3128"),
        ("http://tok@proxy:8080", "http://proxy:8080"),  # userinfo with no colon
        ("http://proxy.corp:8080", "http://proxy.corp:8080"),  # nothing to strip
        ("http://proxy.corp", "http://proxy.corp"),
        (None, None),
        ("", ""),
    ],
)
def test_redact_proxy_url_strips_userinfo(url, expected):
    assert redact_proxy_url(url) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://u:p@[fe80::1]:8080", "http://[fe80::1]:8080"),
        ("http://u:p@[fe80::1]", "http://[fe80::1]"),
        ("http://[fe80::1]:8080", "http://[fe80::1]:8080"),
    ],
)
def test_redact_proxy_url_keeps_ipv6_brackets(url, expected):
    """An IPv6 proxy host must stay bracketed when userinfo is stripped.

    ``httpx.URL.host`` returns the address unbracketed, so naive reassembly
    yields ``http://fe80::1:8080`` -- ambiguous, and unusable as a proxy server.
    playwright_proxy hands this exact string to Chromium as ``server`` for any
    authenticated IPv6 proxy, so the browser fails where every httpx path works.
    """
    assert redact_proxy_url(url) == expected


def test_redact_proxy_url_output_has_no_secret():
    """The redacted form must not contain the password anywhere."""
    assert "s3cret" not in (redact_proxy_url("http://alice:s3cret@proxy.corp:8080") or "")


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


def test_launch_chromium_forwards_extra_args():
    from unittest.mock import MagicMock

    from vip.auth import _launch_chromium

    pw = MagicMock()
    _launch_chromium(pw, headless=True, proxy=None, args=["--no-proxy-server"])
    assert pw.chromium.launch.call_args.kwargs == {
        "headless": True,
        "args": ["--no-proxy-server"],
    }


def test_disabled_proxy_reaches_the_auth_browser(monkeypatch):
    """The whole point of chromium_launch_args: it must actually be plumbed in.

    With [proxy] enabled = false and an ambient proxy, the login browser must be
    launched with --no-proxy-server, not merely without proxy=.
    """
    from vip.auth import start_interactive_auth

    monkeypatch.setenv("HTTPS_PROXY", "http://gw:3128")
    seen = _launched_proxy(monkeypatch)
    with pytest.raises(Exception, match="stop after launch"):
        start_interactive_auth(
            connect_url="https://connect.internal",
            cache_path=None,
            proxy=ProxyConfig(enabled=False),
        )
    assert seen["proxy"] is None
    assert seen["args"] == ["--no-proxy-server"]


def test_ui_test_browser_context_is_forced_direct_when_disabled(monkeypatch):
    """Same for the in-suite UI browsers, which take launch args from
    ``browser_type_launch_args`` rather than from _launch_chromium."""
    from vip.config import VIPConfig
    from vip_tests.conftest import _ui_browser_launch_args

    monkeypatch.setenv("HTTPS_PROXY", "http://gw:3128")
    cfg = VIPConfig()
    cfg.proxy = ProxyConfig(enabled=False)
    assert _ui_browser_launch_args(cfg) == ["--no-proxy-server"]
    assert _ui_browser_launch_args(VIPConfig()) == []


# ---------------------------------------------------------------------------
# Browser callers pass their navigation target, so the browser and the API
# clients resolve the same proxy even when the target is http://
# ---------------------------------------------------------------------------


@pytest.fixture()
def _split_scheme_proxies(monkeypatch):
    """HTTP_PROXY and HTTPS_PROXY pointing at different gateways."""
    for var in ("ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://http-gw:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://https-gw:2")


def _launched_proxy(monkeypatch) -> dict:
    """Capture the proxy dict handed to ``_launch_chromium``."""
    from vip import auth as auth_mod

    seen: dict = {}

    def fake_launch(pw, *, headless, proxy=None, args=None):
        seen["proxy"] = proxy
        seen["args"] = args
        raise RuntimeError("stop after launch")

    monkeypatch.setattr(auth_mod, "_launch_chromium", fake_launch)
    return seen


def test_interactive_auth_browser_uses_the_proxy_for_its_login_target(
    monkeypatch, _split_scheme_proxies
):
    """The interactive login navigates the primary product URL, so an http://
    product must put the browser on the http proxy -- the same one the API-key
    mint and the product clients will use."""
    from vip.auth import start_interactive_auth

    seen = _launched_proxy(monkeypatch)
    with pytest.raises(Exception, match="stop after launch"):
        start_interactive_auth(connect_url="http://connect.internal", cache_path=None)

    assert seen["proxy"]["server"] == "http://http-gw:1"
    assert seen["proxy"]["server"] == proxy_for_url(
        "http://connect.internal", build_proxy_map(ProxyConfig())
    )


def test_headless_auth_browser_uses_the_proxy_for_its_login_target(
    monkeypatch, _split_scheme_proxies
):
    """Same contract for the headless login path."""
    from vip.auth import start_headless_auth

    seen = _launched_proxy(monkeypatch)
    with pytest.raises(Exception, match="stop after launch"):
        start_headless_auth(
            connect_url="http://connect.internal",
            cache_path=None,
            username="u",
            password="p",
        )

    assert seen["proxy"]["server"] == "http://http-gw:1"


def test_authenticated_page_uses_the_proxy_for_the_workbench_url(
    monkeypatch, tmp_path, _split_scheme_proxies
):
    """``vip cleanup --workbench-url`` drives the Workbench UI, so its browser
    must take the route httpx would take to that same Workbench URL."""
    from vip.auth import InteractiveAuthSession, authenticated_page

    state = tmp_path / "state.json"
    state.write_text('{"cookies": [], "origins": []}')
    session = InteractiveAuthSession(storage_state_path=state, _workbench_url="http://wb.internal")

    seen = _launched_proxy(monkeypatch)
    with pytest.raises(Exception, match="stop after launch"):
        with authenticated_page(session):
            pass

    assert seen["proxy"]["server"] == "http://http-gw:1"


def test_ui_browser_proxy_resolves_an_inferred_scheme_first(monkeypatch, _split_scheme_proxies):
    """A scheme-less --workbench-url must be resolved before picking the proxy.

    ``browser_context_args`` is session-scoped and depends only on ``vip_config``,
    so nothing orders it after a fixture that calls ``resolve_url_scheme``. Using
    the raw URL pins the browser to the https gateway while the URL later
    downgrades to http and the API clients use the http one -- the exact split
    ``_ui_browser_proxy`` exists to prevent.
    """
    from vip.config import VIPConfig
    from vip_tests.conftest import _ui_browser_proxy

    cfg = VIPConfig()
    cfg.workbench.url = "https://wb.internal"
    cfg.workbench.url_scheme_inferred = True

    # Stand in for the live probe: the inferred https:// does not answer, so
    # resolve_url_scheme falls back to http://.
    def fake_resolve(pc, **kwargs):
        pc.url = "http://wb.internal"
        pc.url_scheme_inferred = False
        return pc.url

    monkeypatch.setattr("vip_tests.conftest.resolve_url_scheme", fake_resolve)

    pw_proxy = _ui_browser_proxy(cfg)
    assert pw_proxy is not None
    assert pw_proxy["server"] == "http://http-gw:1"


def test_ui_test_browser_context_uses_the_proxy_for_the_product_url(_split_scheme_proxies):
    """The in-suite UI tests drive the configured products, so their browser
    context must resolve the same proxy the API clients did."""
    from vip.config import VIPConfig
    from vip.proxy import playwright_proxy
    from vip_tests.conftest import _ui_browser_proxy

    cfg = VIPConfig()
    cfg.workbench.url = "http://wb.internal"

    pw_proxy = _ui_browser_proxy(cfg)
    assert pw_proxy is not None
    assert pw_proxy["server"] == "http://http-gw:1"
    assert pw_proxy == playwright_proxy(build_proxy_map(cfg.proxy), "http://wb.internal")


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

    # No sleep barrier needed: the .get() above is synchronous and only raises
    # after the proxy has accepted the connection, recorded the request line,
    # and returned its 502 — so any hit is already recorded once we get here.
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

    # No sleep barrier: an erroneously-proxied request would have connected to
    # the proxy synchronously *inside* the .get() above (before it raised), so a
    # stray hit would already be recorded here. Direct path: DNS for the .invalid
    # host fails and the proxy is never contacted.
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

    # No sleep barrier (see test_base_client_no_proxy_host_bypasses): a proxied
    # request would already be recorded synchronously before .get() raised.
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
