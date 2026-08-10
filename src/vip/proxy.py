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

try:
    from httpx._utils import (
        URLPattern,
        get_environment_proxies,
        is_ipv4_hostname,
        is_ipv6_hostname,
    )
except ImportError as exc:  # pragma: no cover - guards a future httpx internals move
    # vip.proxy's entire contract is to mirror httpx's env-proxy resolution
    # byte-for-byte (NO_PROXY formatting, the NO_PROXY=* short-circuit,
    # most-specific-pattern selection). Those helpers live in httpx._utils. If a
    # future httpx relocates them we must NOT degrade silently: build_proxy_map's
    # explicit-url branch needs no internals and would still proxy the pooled
    # clients, while proxy_for_url would return None — sending the mint, probe,
    # delete, and fetch_content bare calls *direct* with trust_env=False. That is
    # worse than the pre-proxy behaviour and a cleartext-credential hazard on a
    # proxy-only host, exactly the split this module exists to remove. Fail loud
    # and early, pointing at the supported pin, instead.
    raise ImportError(
        "vip.proxy requires httpx's internal env-proxy helpers "
        "(httpx._utils.URLPattern / get_environment_proxies / is_ipv4_hostname / "
        f"is_ipv6_hostname), which are missing from the installed httpx {httpx.__version__}. "
        "VIP supports httpx>=0.27,<1 — pin httpx within that range. Continuing would "
        "route some HTTP egress around the configured proxy, so VIP refuses to start "
        "rather than degrade silently."
    ) from exc


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
            url=str(raw.get("url", "")),
            no_proxy=_as_host_list(raw.get("no_proxy", [])),
            enabled=_as_bool(raw.get("enabled", True), field="[proxy] enabled"),
            trust_env=_as_bool(raw.get("trust_env", True), field="[proxy] trust_env"),
        )


def _as_host_list(value: object) -> list[str]:
    """Normalize a ``no_proxy`` value (list, or comma-separated string) to a list."""
    if isinstance(value, str):
        return [h.strip() for h in value.split(",") if h.strip()]
    if isinstance(value, list):
        return [str(h).strip() for h in value if str(h).strip()]
    return []


def _as_bool(value: object, *, field: str) -> bool:
    """Reject a non-boolean where a TOML boolean is required.

    TOML has a real boolean type, so ``enabled = false`` parses to ``False``.
    But ``enabled = "false"`` parses to the *string* ``"false"`` — truthy — which
    would silently turn proxying **on** for a user who meant to turn it off (and,
    for a security-sensitive toggle, in the more dangerous direction). Fail fast
    on a config typo rather than honour the wrong value, matching
    :func:`vip.config._validate_cert_expiry_warning_days`'s fail-loud convention
    for fields whose wrong value doesn't otherwise error on first use.
    """
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field} must be a boolean (true/false), got {value!r}")


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


def redact_proxy_url(url: str | None) -> str | None:
    """Strip any ``user:pass@`` userinfo from a proxy URL for safe logging.

    An authenticated forward proxy is commonly configured as
    ``http://user:pass@proxy.corp:8080`` (via ``HTTPS_PROXY``, ``[proxy] url``,
    or ``--proxy``), and :func:`proxy_for_url` returns that URL verbatim. Any
    warning/log line that names the applicable proxy must route the value
    through here first so the password never lands in stdout or CI logs.
    Returns the input unchanged when it has no userinfo or cannot be parsed.
    """
    if not url:
        return url
    try:
        parsed = httpx.URL(url)
    except Exception:
        return url
    if not (parsed.username or parsed.password):
        return url
    hostport = parsed.host if parsed.port is None else f"{parsed.host}:{parsed.port}"
    return f"{parsed.scheme}://{hostport}"


def _no_proxy_pattern(hostname: str) -> str:
    """Return the httpx URL-pattern key for a single ``NO_PROXY`` host.

    Mirrors :func:`httpx._utils.get_environment_proxies` byte-for-byte so an
    explicit ``[proxy] no_proxy`` behaves identically to the same host given
    via the ``NO_PROXY`` environment variable.
    """
    if "://" in hostname:
        return hostname
    if is_ipv4_hostname(hostname):
        return f"all://{hostname}"
    if is_ipv6_hostname(hostname):
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

    # A bare "*" in no_proxy means "bypass the proxy for everything", exactly as
    # httpx's get_environment_proxies short-circuits NO_PROXY=* to an empty map.
    # httpx only applies this to the *environment* NO_PROXY; we extend it to the
    # explicit [proxy] no_proxy so `no_proxy = ["*"]` (and --no-proxy '*') behave
    # identically to the env var rather than emitting a useless `all://**`
    # pattern that never matches and leaves everything still proxied.
    if "*" in config.no_proxy:
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

    if config.trust_env:
        # Reuse httpx's own environment parsing so VIP inherits its key format,
        # NO_PROXY semantics, and NO_PROXY=* short-circuit.
        proxy_map = dict(get_environment_proxies())
        _promote_http_proxy_to_https(proxy_map)
        # An env map of {} means NO_PROXY=* (bypass everything) or no proxy at
        # all — in both cases adding bypass holes is meaningless, so only merge
        # config.no_proxy when the environment actually configured a proxy.
        if proxy_map:
            for host in config.no_proxy:
                proxy_map[_no_proxy_pattern(host)] = None
        return proxy_map

    return {}


def _promote_http_proxy_to_https(proxy_map: ProxyMap) -> None:
    """Extend a lone ``HTTP_PROXY`` to also carry https traffic, in place.

    A deliberate divergence from httpx's env parsing. httpx keys its proxy map
    by the *target* scheme, so ``HTTP_PROXY=http://gw:3128`` alone yields
    ``{"http://": ...}`` with no ``https://`` entry — and httpx therefore sends
    https **direct**. That's fine for a general HTTP client, but many
    organisations run a single forward proxy as their *only* outbound tunnel and
    set just ``http_proxy``, expecting all egress — including https, via the
    proxy's ``CONNECT`` tunnel — to flow through it. On such a proxy-only network
    the httpx default means VIP's https product traffic can never leave the host.

    (The scheme in ``http://gw:3128`` describes how VIP talks *to the proxy*, not
    what the proxy may carry: an HTTP proxy tunnels https end-to-end via
    ``CONNECT``, so pointing https at it is valid.)

    So when the environment gave us an ``http://`` proxy but named neither an
    ``https://`` proxy (``HTTPS_PROXY``) nor a catch-all (``ALL_PROXY`` →
    ``all://``), reuse the http proxy for https as well. If the operator set an
    explicit ``HTTPS_PROXY`` or ``ALL_PROXY``, that stands — we never override a
    deliberate choice, and a per-host ``NO_PROXY`` still bypasses (its
    ``all://*host`` pattern is more specific than the promoted ``https://``).
    """
    http_proxy = proxy_map.get("http://")
    if http_proxy and "https://" not in proxy_map and "all://" not in proxy_map:
        proxy_map["https://"] = http_proxy


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
    if not proxy_map:
        return None
    target = httpx.URL(url)
    # Match httpx exactly: URLPattern sorts ascending with the *most specific*
    # pattern first (a host pattern like ``all://*foo`` has a smaller priority
    # tuple than the catch-all ``all://``), and the first matching pattern wins.
    # So a NO_PROXY host beats the catch-all proxy and correctly resolves to
    # None (bypass) — the whole point of consulting this for the #2 tiebreak.
    for pattern in sorted(URLPattern(k) for k in proxy_map):
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

    Playwright accepts a ``server`` plus optional ``username`` / ``password`` and
    a comma-separated ``bypass`` list. The browser login navigates https Posit
    product URLs, so the server is the proxy an https URL would select (see
    :func:`_primary_proxy_server`), keeping the browser on the same route as the
    httpx paths. The ``bypass`` list is the map's bypass (``None``-valued)
    patterns rendered back to bare hostnames. Returns ``None`` when no proxy
    applies to the browser's https traffic, so the caller launches Chromium
    exactly as before.

    An authenticated proxy is commonly given as ``http://user:pass@proxy:8080``.
    httpx parses that userinfo into its own proxy auth, but Chromium **ignores**
    credentials embedded in the proxy server string — Playwright expects them in
    separate ``username`` / ``password`` fields. Passing the raw URL as ``server``
    would make the browser log in fail with a 407 while every httpx path
    authenticates fine: exactly the browser-vs-API split this module exists to
    remove. So split any userinfo out of the server URL into ``username`` /
    ``password`` and hand Playwright a credential-free ``server``.
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
    username, password = _split_proxy_userinfo(server)
    if username is not None:
        proxy["server"] = redact_proxy_url(server) or server
        proxy["username"] = username
        proxy["password"] = password or ""
    bypass = ",".join(h for h in bypass_hosts if h)
    if bypass:
        proxy["bypass"] = bypass
    return proxy


def _split_proxy_userinfo(url: str) -> tuple[str | None, str | None]:
    """Return the ``(username, password)`` embedded in a proxy URL, or ``(None, None)``.

    Mirrors what :func:`redact_proxy_url` parses, but returns the credentials so
    :func:`playwright_proxy` can hand them to Playwright's dedicated fields
    rather than leaving them in the ``server`` string (which Chromium drops).
    Returns ``(None, None)`` when the URL has no userinfo or cannot be parsed, so
    an unauthenticated proxy is passed through as a bare ``server`` unchanged.
    """
    try:
        parsed = httpx.URL(url)
    except Exception:
        return None, None
    if not (parsed.username or parsed.password):
        return None, None
    return parsed.username, parsed.password


def _primary_proxy_server(proxy_map: ProxyMap) -> str | None:
    """Pick the single proxy server Playwright should use for the browser login.

    The browser login always navigates **https** Posit product URLs, so it uses
    the proxy an https URL would select: an ``https://`` key (an explicit
    ``HTTPS_PROXY``, or the http->https promotion in
    :func:`_promote_http_proxy_to_https` that lets a lone ``HTTP_PROXY`` tunnel
    https too) or a catch-all ``all://`` (``--proxy`` / ``[proxy] url`` /
    ``ALL_PROXY``). This is exactly what :func:`proxy_for_url` returns for an
    https URL, so the browser and every httpx path take the same route by
    construction — no independent scheme fallback that could diverge. Returns
    ``None`` only when no proxy applies to https (the map has neither key), in
    which case httpx sends https direct and the browser must too.
    """
    for key in ("https://", "all://"):
        value = proxy_map.get(key)
        if value:
            return value
    return None


def _pattern_to_bypass_host(pattern: str) -> str:
    """Convert an httpx bypass pattern back to a Playwright bypass hostname.

    Inverse of :func:`_no_proxy_pattern`: ``all://*.foo`` → ``*.foo``,
    ``all://*foo`` → ``*foo``, ``all://host`` → ``host``, ``all://[::1]`` → ``::1``.

    The leading ``*`` is deliberately **kept**. httpx renders a bare
    ``NO_PROXY=example.com`` as ``all://*example.com``, whose match set is
    ``example.com`` *and* ``www.example.com``. Chromium's bypass grammar reads a
    bare ``example.com`` as an exact-host match, so stripping the ``*`` would
    make the browser proxy exactly the subdomains every httpx path reaches
    directly — and Posit products live on subdomains, so that is the case that
    matters. ``*example.com`` is a valid Chromium HOSTNAME_PATTERN covering both,
    and Playwright forwards it unchanged (it only prepends ``*`` to entries that
    already start with ``.``, which leaves ``*.foo`` alone as well).
    """
    host = pattern.removeprefix("all://").removeprefix("http://").removeprefix("https://")
    return host.strip("[]")
