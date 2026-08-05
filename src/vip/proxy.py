"""Outbound-proxy resolution — the single source of truth for VIP's HTTP egress.

VIP talks to Posit deployments over several different HTTP mechanisms (a shared
``httpx.Client`` with a custom transport for the product API clients, bare
``httpx.get`` for probes and content fetches, and Playwright's Chromium for the
browser login). Left to their own devices these disagree about outbound
proxies: a custom-transport ``httpx.Client`` silently ignores ``HTTP_PROXY`` /
``HTTPS_PROXY`` (in httpx, ``allow_env_proxies = trust_env and transport is
None`` — a supplied transport shuts env-proxy resolution off entirely), while
bare ``httpx.get`` honours them. That split is exactly what makes VIP misbehave
behind an outbound proxy.

This module centralises proxy resolution so every egress path makes the *same*
decision:

* :func:`build_proxy_map` turns a :class:`ProxyConfig` (explicit config, or
  "read the environment") into an httpx-style proxy map — the same
  ``{pattern: proxy_or_None}`` shape httpx builds internally, with ``NO_PROXY``
  entries formatted identically to :func:`httpx._utils.get_environment_proxies`.
* :func:`build_mounts` turns that map into per-pattern ``httpx.HTTPTransport``
  mounts (each carrying the caller's ``verify`` setting) suitable for
  ``httpx.Client(transport=<base>, mounts=<these>)``.
* :func:`proxy_for_url` answers "which proxy (if any) applies to this URL",
  reproducing httpx's own most-specific-pattern-wins selection. This is what
  lets a non-httpx probe (a raw socket, Playwright) take the *same* network
  path the API clients will.
* :func:`playwright_proxy` renders the map as a Playwright ``proxy=`` dict so
  the browser login traverses the same proxy as everything else, rather than
  relying on Chromium's implicit, platform-dependent env detection.

A note on retries: when a proxy is configured, httpx's ``HTTPTransport`` builds
an ``httpcore.HTTPProxy`` pool, which does **not** carry the ``retries`` value
(only the direct ``ConnectionPool`` does). So proxied requests get no
connection-level retries — this is httpx's behaviour, matched here deliberately
rather than worked around.
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass, field

import httpx

try:  # httpx keeps these in _utils; import defensively so a future move is loud, not silent.
    from httpx._utils import (
        URLPattern,
        get_environment_proxies,
        is_ipv4_hostname,
        is_ipv6_hostname,
    )

    _HTTPX_INTERNALS = True
except ImportError:  # pragma: no cover - exercised only if httpx reorganises internals
    URLPattern = None  # type: ignore[assignment,misc]
    get_environment_proxies = None  # type: ignore[assignment]
    is_ipv4_hostname = None  # type: ignore[assignment]
    is_ipv6_hostname = None  # type: ignore[assignment]
    _HTTPX_INTERNALS = False


# A proxy map matches httpx's internal shape: URL-pattern string -> proxy URL,
# or ``None`` to mean "bypass the proxy for URLs matching this pattern".
ProxyMap = dict[str, "str | None"]


@dataclass
class ProxyConfig:
    """How VIP should resolve its outbound proxy.

    Three modes, in the order :func:`build_proxy_map` resolves them:

    * ``enabled=False`` — proxying is turned **off**, even if proxy environment
      variables are set. Every request goes direct. This is how ``--no-proxy``
      with no hosts, or ``[proxy] enabled = false``, forces a direct path.
    * ``url`` set — an **explicit** proxy. All traffic is routed through *url*
      except hosts in *no_proxy* (which are formatted exactly as httpx formats
      ``NO_PROXY``). Overrides the environment.
    * neither — when ``trust_env`` is true (the default), read the ambient
      ``HTTP_PROXY`` / ``HTTPS_PROXY`` / ``ALL_PROXY`` / ``NO_PROXY`` exactly as
      httpx's bare-client paths already do; when false, go direct.
    """

    url: str = ""
    no_proxy: list[str] = field(default_factory=list)
    enabled: bool = True
    trust_env: bool = True

    @classmethod
    def from_dict(cls, raw: dict) -> ProxyConfig:
        return cls(
            url=raw.get("url", ""),
            no_proxy=_as_host_list(raw.get("no_proxy", [])),
            enabled=raw.get("enabled", True),
            trust_env=raw.get("trust_env", True),
        )

    @property
    def is_active(self) -> bool:
        """True when this config can produce at least one proxy route.

        Cheap enough to compute without building the whole map; used by
        callers that only need to know "is a proxy in play at all?".
        """
        return bool(build_proxy_map(self))


def _as_host_list(value: object) -> list[str]:
    """Normalize a ``no_proxy`` value (list, or comma-separated string) to a list."""
    if isinstance(value, str):
        return [h.strip() for h in value.split(",") if h.strip()]
    if isinstance(value, list):
        return [str(h).strip() for h in value if str(h).strip()]
    return []


def _normalize_proxy_url(url: str) -> str:
    """Default a scheme-less proxy URL to ``http://``, mirroring httpx.

    httpx's own env parsing does ``hostname if "://" in hostname else
    f"http://{hostname}"`` (:func:`httpx._utils.get_environment_proxies`). An
    explicit ``[proxy] url = "proxy:8080"`` (or ``--proxy proxy:8080``) would
    otherwise reach ``httpx.Proxy()`` verbatim and raise "Unknown scheme for
    proxy URL". Applying the same default keeps the explicit path consistent
    with the environment path.
    """
    return url if "://" in url else f"http://{url}"


def _no_proxy_pattern(hostname: str) -> str:
    """Return the httpx URL-pattern key for a single ``NO_PROXY`` host.

    Mirrors :func:`httpx._utils.get_environment_proxies` byte-for-byte so an
    explicit ``[proxy] no_proxy`` behaves identically to the same host given
    via the ``NO_PROXY`` environment variable.
    """
    if "://" in hostname:
        return hostname
    if _HTTPX_INTERNALS and is_ipv4_hostname(hostname):  # type: ignore[misc]
        return f"all://{hostname}"
    if _HTTPX_INTERNALS and is_ipv6_hostname(hostname):  # type: ignore[misc]
        return f"all://[{hostname}]"
    if hostname.lower() == "localhost":
        return f"all://{hostname}"
    return f"all://*{hostname}"


def build_proxy_map(config: ProxyConfig | None) -> ProxyMap:
    """Resolve *config* into an httpx-style proxy map.

    Returns an empty map (``{}`` — every request direct) when proxying is
    disabled, when there is no explicit proxy and ``trust_env`` is off, or when
    the environment simply has no proxy set. See :class:`ProxyConfig` for the
    resolution order.
    """
    if config is None:
        config = ProxyConfig()

    if not config.enabled:
        return {}

    if config.url:
        # Explicit proxy: route everything (both schemes) through it, then
        # punch bypass holes for each no_proxy host. ``all://`` is used rather
        # than separate http/https keys so a single --proxy covers both. The URL
        # is scheme-normalized (a bare ``proxy:8080`` → ``http://proxy:8080``)
        # exactly as httpx's own env parsing does, so httpx.Proxy() never raises
        # "Unknown scheme for proxy URL".
        proxy_map: ProxyMap = {"all://": _normalize_proxy_url(config.url)}
        for host in config.no_proxy:
            proxy_map[_no_proxy_pattern(host)] = None
        return proxy_map

    if config.trust_env and _HTTPX_INTERNALS:
        # Reuse httpx's own environment parsing so VIP never diverges from it —
        # same key format, same NO_PROXY semantics, same NO_PROXY=* short-circuit.
        proxy_map = dict(get_environment_proxies())  # type: ignore[misc]
        # An env map of {} means NO_PROXY=* (bypass everything) or no proxy at
        # all — in both cases adding bypass holes is meaningless, so only merge
        # config.no_proxy when the environment actually configured a proxy.
        if proxy_map:
            for host in config.no_proxy:
                proxy_map[_no_proxy_pattern(host)] = None
        return proxy_map

    return {}


def build_mounts(
    proxy_map: ProxyMap,
    *,
    verify: bool | str = True,
    retries: int = 3,
) -> dict[str, httpx.BaseTransport]:
    """Build httpx ``mounts`` from a proxy map, preserving *verify*.

    Each entry becomes an :class:`httpx.HTTPTransport`:

    * a real proxy URL → a transport whose pool proxies through it, and
    * ``None`` (a bypass pattern) → a plain direct transport,

    both carrying *verify* so TLS configuration is honoured on the transport
    (a custom transport makes httpx ignore the *client*-level ``verify``, so it
    must live here). Pass the result as ``httpx.Client(mounts=...)`` alongside a
    base ``transport=`` that handles URLs matching no pattern.

    Returns an empty dict for an empty map, so a proxy-less client is byte-for-
    byte the same as before this module existed (no mounts → base transport
    handles everything).
    """
    mounts: dict[str, httpx.BaseTransport] = {}
    for pattern, proxy_url in proxy_map.items():
        if proxy_url is None:
            # Bypass: a direct transport for this pattern. retries applies here
            # (a direct ConnectionPool honours it, unlike the proxy pool).
            mounts[pattern] = httpx.HTTPTransport(retries=retries, verify=verify)
        else:
            mounts[pattern] = httpx.HTTPTransport(
                retries=retries, verify=verify, proxy=httpx.Proxy(proxy_url)
            )
    return mounts


def proxy_for_url(url: str, proxy_map: ProxyMap) -> str | None:
    """Return the proxy URL that applies to *url*, or ``None`` if it goes direct.

    Reproduces httpx's selection: build a :class:`URLPattern` per key, sort so
    the most specific pattern wins, and return the first match's value (which is
    ``None`` for a bypass pattern). Callers that are not httpx clients — a raw
    socket probe, Playwright — use this to take the *same* network path the API
    clients will, instead of a divergent one.
    """
    if not proxy_map or not _HTTPX_INTERNALS:
        return None
    target = httpx.URL(url)
    # Match httpx exactly: URLPattern sorts ascending with the *most specific*
    # pattern first (a host pattern like ``all://*foo`` has a smaller priority
    # tuple than the catch-all ``all://``), and the first matching pattern wins.
    # So a NO_PROXY host beats the catch-all proxy and correctly resolves to
    # None (bypass) — the whole point of consulting this for the #2 tiebreak.
    for pattern in sorted(URLPattern(k) for k in proxy_map):  # type: ignore[misc]
        if pattern.matches(target):
            return proxy_map[pattern.pattern]
    return None


def verify_with_env_ca(verify: bool | str) -> bool | str | ssl.SSLContext:
    """Preserve ``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` when a caller pins ``trust_env=False``.

    VIP's proxy-aware egress pins ``trust_env=False`` on its ad-hoc httpx calls
    so the proxy it resolved stays authoritative (httpx would otherwise re-read
    the proxy environment and could disagree with a ``NO_PROXY`` bypass). But
    ``trust_env`` also gates httpx's honoring of the ``SSL_CERT_FILE`` /
    ``SSL_CERT_DIR`` CA overrides — a common way to trust a corporate CA without
    editing ``vip.toml``. Turning it off wholesale would silently drop that CA
    on these calls while the pooled clients (whose transport uses ``trust_env``'s
    default) still honor it — an inconsistent TLS path within one run.

    So when verification is on with the system trust store (``verify is True``),
    bake the environment's CA overrides into an :class:`ssl.SSLContext` and
    return it as the ``verify`` value. ``False`` (insecure) and a ``str`` CA
    bundle path are authoritative and returned unchanged.
    """
    if verify is not True:
        return verify
    return httpx.create_ssl_context(verify=True, trust_env=True)


def playwright_proxy(proxy_map: ProxyMap) -> dict[str, str] | None:
    """Render *proxy_map* as a Playwright ``launch(proxy=...)`` dict, or ``None``.

    Playwright accepts a single ``server`` plus a comma-separated ``bypass``
    list, so a map that proxies http and https through different servers cannot
    be expressed exactly; https wins because Posit product URLs are https. The
    ``bypass`` list is the map's bypass (``None``-valued) patterns rendered back
    to bare hostnames. Returns ``None`` when the map configures no proxy, so the
    caller launches Chromium exactly as before.
    """
    server = _primary_proxy_server(proxy_map)
    if server is None:
        return None
    bypass_hosts = [
        _pattern_to_bypass_host(pattern)
        for pattern, proxy_url in proxy_map.items()
        if proxy_url is None
    ]
    proxy: dict[str, str] = {"server": server}
    bypass = ",".join(h for h in bypass_hosts if h)
    if bypass:
        proxy["bypass"] = bypass
    return proxy


def _primary_proxy_server(proxy_map: ProxyMap) -> str | None:
    """Pick the single proxy server Playwright should use (prefer https, then all)."""
    for key in ("https://", "all://"):
        value = proxy_map.get(key)
        if value:
            return value
    # Fall back to any non-None proxy value present.
    for value in proxy_map.values():
        if value:
            return value
    return None


def _pattern_to_bypass_host(pattern: str) -> str:
    """Convert an httpx bypass pattern back to a Playwright bypass hostname.

    Inverse of :func:`_no_proxy_pattern`: ``all://*.foo`` → ``.foo``,
    ``all://host`` → ``host``, ``all://[::1]`` → ``::1``.
    """
    host = pattern.removeprefix("all://").removeprefix("http://").removeprefix("https://")
    host = host.removeprefix("*")
    return host.strip("[]")
