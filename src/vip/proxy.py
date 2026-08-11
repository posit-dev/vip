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
    """Normalize a ``no_proxy`` value (list, or comma-separated string) to a list.

    Anything else is a config typo and raises, rather than silently yielding an
    empty list. A dropped bypass list is the same class of failure
    :func:`_as_bool` rejects below, and it fails in the same direction: hosts the
    operator meant to keep off the proxy get tunnelled through it, with nothing
    in the output to say so.
    """
    if isinstance(value, str):
        return [h.strip() for h in value.split(",") if h.strip()]
    if isinstance(value, list):
        return [str(h).strip() for h in value if str(h).strip()]
    raise ValueError(
        f"[proxy] no_proxy must be a list of hosts or a comma-separated string, got {value!r}"
    )


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
    # ``httpx.URL.host`` returns an IPv6 address unbracketed, so reassembling it
    # naively gives ``http://fe80::1:8080`` -- ambiguous, and unusable as a proxy
    # server string (playwright_proxy hands this straight to Chromium).
    host = f"[{parsed.host}]" if ":" in parsed.host else parsed.host
    hostport = host if parsed.port is None else f"{host}:{parsed.port}"
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


def playwright_proxy(proxy_map: ProxyMap, target_url: str | None = None) -> dict[str, str] | None:
    """Render *proxy_map* as a Playwright ``launch(proxy=...)`` dict, or ``None``.

    Playwright accepts a ``server`` plus optional ``username`` / ``password`` and
    a comma-separated ``bypass`` list. *target_url* is the URL the browser will
    navigate; its scheme picks the proxy, so the browser takes the route
    :func:`proxy_for_url` would give that URL rather than assuming https (see
    :func:`_primary_proxy_server`). Omit it only when there is no single
    navigation target, in which case https-first selection applies. The
    ``bypass`` list is the map's bypass (``None``-valued) patterns rendered back
    to hostname patterns. Returns ``None`` when no proxy applies at all, so the
    caller launches Chromium exactly as before.

    Note that *target_url* chooses *which* proxy, not *whether* there is one: a
    target on the bypass list still yields a dict, because the login browser does
    not stay on one host — it follows a redirect to the IdP, which usually is not
    bypassed and does need the proxy. Chromium applies ``bypass`` per request, so
    the target itself still goes direct.

    An authenticated proxy is commonly given as ``http://user:pass@proxy:8080``.
    httpx parses that userinfo into its own proxy auth, but Chromium **ignores**
    credentials embedded in the proxy server string — Playwright expects them in
    separate ``username`` / ``password`` fields. Passing the raw URL as ``server``
    would make the browser log in fail with a 407 while every httpx path
    authenticates fine: exactly the browser-vs-API split this module exists to
    remove. So split any userinfo out of the server URL into ``username`` /
    ``password`` and hand Playwright a credential-free ``server``.
    """
    server = _primary_proxy_server(proxy_map, target_url)
    if server is None:
        return None
    bypass_hosts = [
        entry
        for pattern, proxy_url in proxy_map.items()
        if proxy_url is None
        for entry in _pattern_to_bypass_hosts(pattern)
    ]
    # When the chosen server is a fallback -- httpx would reach *target_url*
    # directly, but the browser still needs a proxy for the hops that follow --
    # bypass the target explicitly. Otherwise Chromium sends a plain-http request
    # for an http:// product to an https gateway that will 403/407 it, while
    # every httpx call to the same host goes direct.
    if target_url and proxy_for_url(target_url, proxy_map) is None:
        if not _matches_a_bypass_pattern(target_url, proxy_map):
            # Only when nothing in the map already covers it -- a target the
            # NO_PROXY patterns match is bypassed by those, and re-listing its
            # exact host would just add noise Chromium has to parse.
            target_host = _bypass_host_for_url(target_url)
            if target_host and target_host not in bypass_hosts:
                bypass_hosts.append(target_host)
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


def _matches_a_bypass_pattern(url: str, proxy_map: ProxyMap) -> bool:
    """Whether *url* resolves to direct because a bypass pattern matched it.

    :func:`proxy_for_url` returns ``None`` both for "a bypass pattern won" and
    for "no pattern matched at all"; only the second needs the target adding to
    Playwright's bypass list.
    """
    try:
        target = httpx.URL(url)
    except Exception:
        return False
    for pattern in sorted(URLPattern(k) for k in proxy_map):
        if pattern.matches(target):
            return proxy_map[pattern.pattern] is None
    return False


def _bypass_host_for_url(url: str) -> str | None:
    """The Chromium bypass entry for *url*'s host, or ``None`` if unparseable.

    IPv6 literals are re-bracketed: ``httpx.URL.host`` strips the brackets, and
    Chromium's bypass grammar reads the bare form with ``:`` as a port separator.
    """
    try:
        host = httpx.URL(url).host
    except Exception:
        return None
    if not host:
        return None
    return f"[{host}]" if ":" in host else host


def chromium_launch_args(config: ProxyConfig | None) -> list[str]:
    """Extra Chromium switches needed to honor *config*, beyond ``proxy=``.

    Returns ``["--no-proxy-server"]`` when the user has **explicitly** turned
    proxying off (``[proxy] enabled = false``, ``--no-proxy ''``, or
    ``trust_env = false``), and ``[]`` otherwise.

    This exists because omitting Playwright's ``proxy=`` does not tell Chromium
    "go direct" — it tells it "decide for yourself", and Chromium then reads the
    ambient ``http_proxy``/``https_proxy`` (on Linux) or the system proxy
    settings. :func:`playwright_proxy` returns ``None`` both when nothing is
    configured and when proxying is explicitly disabled, and those two must not
    behave the same: the second is the one case where the user has demanded a
    direct path, and it is exactly where the browser would otherwise proxy while
    every httpx call goes direct.

    ``--no-proxy-server`` is the switch that actually forces it. Playwright's
    ``normalizeProxySettings`` rewrites a ``direct://`` server (empty host) into
    ``http://direct://``, i.e. a real proxy, so passing that through ``proxy=``
    is not an alternative.

    "Nothing configured" deliberately returns ``[]`` — Chromium is left exactly
    as it behaved before this module existed.
    """
    if config is None:
        return []
    if not config.enabled or (not config.url and not config.trust_env):
        return ["--no-proxy-server"]
    return []


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


def _primary_proxy_server(proxy_map: ProxyMap, target_url: str | None = None) -> str | None:
    """Pick the single proxy server Playwright should use for the browser login.

    Playwright takes one ``server`` per browser and normalises it to a single
    ``scheme://host:port`` (its ``normalizeProxySettings`` rewrites the value, so
    Chromium's per-scheme ``--proxy-server=http=a;https=b`` form is not an
    option). We therefore pick the proxy for the scheme of *target_url* — the URL
    the browser is about to navigate — so the browser and every httpx path take
    the same route by construction.

    That scheme matters whenever the two differ. With ``HTTP_PROXY`` and
    ``HTTPS_PROXY`` pointing at different gateways and a product served over
    plain http (TLS terminated upstream, or an inferred https URL that
    :func:`~vip.auth.resolve_url_scheme` downgraded), always selecting the https
    key would hand Chromium the https gateway while every httpx call used the
    http one — the browser/API split this module exists to remove.

    Without *target_url* (no single navigation target) the https key wins, then
    the catch-all: an explicit ``HTTPS_PROXY``, or the http->https promotion in
    :func:`_promote_http_proxy_to_https` that lets a lone ``HTTP_PROXY`` tunnel
    https, or ``all://`` from ``--proxy`` / ``[proxy] url`` / ``ALL_PROXY``.

    *target_url* chooses *which* proxy, never *whether* there is one: when its
    scheme has no key we fall through to the map's other proxies rather than
    returning ``None``. A browser is not single-host — an http:// product login
    redirects straight to an https IdP that httpx proxies — so dropping the
    proxy because the first hop does not need it would leave the browser as the
    only thing on the box that cannot reach the IdP. ``None`` therefore means
    exactly one thing: the map has no proxy at all, so httpx goes direct too.
    """
    if target_url:
        try:
            scheme = httpx.URL(target_url).scheme
        except Exception:
            scheme = ""
        if scheme == "http":
            keys = ("http://", "all://", "https://")
        else:
            keys = ("https://", "all://", "http://")
    else:
        keys = ("https://", "all://", "http://")
    for key in keys:
        value = proxy_map.get(key)
        if value:
            return value
    return None


def _pattern_to_bypass_hosts(pattern: str) -> list[str]:
    """Convert an httpx bypass pattern into the Playwright bypass entries that
    reproduce its match set exactly.

    Inverse of :func:`_no_proxy_pattern`. The three forms and why they differ:

    * ``all://*foo`` (from a bare ``NO_PROXY=foo``) → ``["foo", "*.foo"]``.
      httpx compiles this to ``^(.+\\.)?foo$`` — the apex *and* dot-separated
      subdomains, but explicitly not ``badfoo``. Chromium has no single pattern
      with that match set: a bare ``foo`` is exact-host only (too narrow, so the
      browser would proxy subdomains httpx reaches directly), while ``*foo`` is a
      plain glob that also swallows ``badfoo`` (too wide, so the browser would go
      direct where httpx proxies — a wider hole than the one it closes). Two
      entries give the apex and the subdomains and nothing else.
    * ``all://*.foo`` (from ``NO_PROXY=.foo``) → ``["*.foo"]``. httpx's
      ``^.+\\.foo$`` is subdomains only, which ``*.foo`` matches exactly.
    * ``all://host`` (an IP or ``localhost``) → the bare host. IPv6 keeps its
      brackets (``all://[::1]`` → ``["[::1]"]``): Chromium's bypass grammar wants
      an IP_LITERAL bracketed, and reads the bare ``::1`` with ``:`` as a port
      separator, so it never matches and the entry silently does nothing.
    * A CIDR mask is **dropped** (``all://10.0.0.0/8`` → ``["10.0.0.0"]``).
      httpx's ``URLPattern`` parses ``/8`` as a URL path and ignores it, leaving
      the host regex ``^10\\.0\\.0\\.0$`` — the literal address only, never the
      range. Chromium *does* implement CIDR bypass rules, so forwarding the mask
      would bypass every host in the range while every httpx call to those same
      hosts is proxied. Parity with httpx is the contract here, so match its
      (admittedly limited) behavior rather than invent a wider one.

    Playwright forwards these unchanged; it only prepends ``*`` to entries that
    already start with ``.``.
    """
    host = pattern.removeprefix("all://").removeprefix("http://").removeprefix("https://")
    # Drop a CIDR mask, mirroring what httpx's URLPattern does with it.
    host = host.split("/", 1)[0]

    # Split into the literal domain httpx will match on and the Chromium entries
    # that reproduce it, following the same three branches httpx's URLPattern uses
    # to build its host regex.
    if host.startswith("*."):
        domain, entries = host[2:], [f"*.{host[2:]}"]
    elif host.startswith("*"):
        domain, entries = host[1:], [host[1:], f"*.{host[1:]}"]
    else:
        domain, entries = host, [host]

    if "*" in domain:
        # httpx escapes the host into its regex, so a ``*`` surviving into the
        # literal domain means the pattern demands a literal ``*`` in the
        # hostname and can never match anything real -- ``NO_PROXY=*.foo.com``
        # becomes ``^(.+\\.)?\\*\\.foo\\.com$``. Chromium's grammar *does* glob,
        # so emitting an entry here would bypass every subdomain in the browser
        # while every httpx call is proxied, silently escaping a mandated proxy.
        # NO_PROXY has no wildcard syntax; httpx's reading is that this matches
        # nothing, and the browser has to agree.
        return []
    return entries
