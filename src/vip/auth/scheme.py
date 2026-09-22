"""URL scheme resolution, the TLS-listener probe, and httpx ``verify`` helpers."""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from vip.proxy import (
    ProxyConfig,
    build_proxy_map,
    proxy_for_url,
    redact_proxy_url,
    verify_with_env_ca,
)
from vip.timeouts import scaled

if TYPE_CHECKING:
    from vip.config import ProductConfig


def _httpx_verify(insecure: bool, ca_bundle: Path | None) -> bool | str:
    """Derive the httpx ``verify`` value from TLS config parameters.

    - ``insecure=True`` → ``False`` (skip verification; insecure wins over ca_bundle)
    - ``ca_bundle`` set → ``str`` path to the bundle file
    - default → ``True`` (system trust store)

    Mirrors ``vip.cli._common._resolve_effective_ca_bundle`` and
    ``VIPConfig.verify`` so TLS behaviour is consistent across every httpx
    call site in the auth package.
    """
    if insecure:
        return False
    if ca_bundle is not None:
        return str(ca_bundle)
    return True


def _httpx_verify_env_aware(insecure: bool, ca_bundle: Path | None) -> bool | str | ssl.SSLContext:
    """Like :func:`_httpx_verify`, but preserves ``SSL_CERT_FILE`` / ``SSL_CERT_DIR``.

    The bare-httpx calls in this module pin ``trust_env=False`` so the proxy VIP
    resolved is authoritative (httpx would otherwise re-read the proxy
    environment and could disagree with a ``NO_PROXY`` bypass). ``trust_env``
    also gates httpx's honoring of the ``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` CA
    overrides, so :func:`vip.proxy.verify_with_env_ca` folds those back into an
    ``ssl.SSLContext`` when verification uses the system trust store. See that
    function for the full rationale.
    """
    return verify_with_env_ca(_httpx_verify(insecure, ca_bundle))


# Cache of resolved schemes, keyed by (url, insecure, ca_bundle, applicable_proxy)
# -- the four inputs that determine what the probe below would decide. A single
# `vip verify` run can reach ``resolve_url_scheme`` from more than one place
# -- the interactive/headless auth flow, then again from a client fixture
# reading the same config value -- so the second and later calls for the
# same key are a dict lookup instead of a second live probe. Keying on URL
# alone would let a cached ``verify=True`` failure silently authorise a
# downgrade for a later caller that actually passed ``insecure=True`` (or a
# different ``ca_bundle``). The proxy is in the key too because a host reachable
# only through a proxy fails a direct probe but succeeds a proxied one, so the
# resolved scheme genuinely differs by which proxy (if any) applies.
_scheme_resolution_cache: dict[tuple[str, bool, Path | None, str | None], str] = {}


def _tls_listener_present(url: str, *, timeout: float) -> bool:
    """True if something accepts a TCP connection at *url*'s host:port.

    Used to tell "TLS is present but this client doesn't trust it" (a
    self-signed, expired, or otherwise unverified certificate; a protocol
    mismatch; any other handshake failure) apart from "nothing is listening
    here" when an https:// probe fails at the transport level. Those are not
    the same failure and must not share a remedy: a listener that completes
    a TCP handshake but fails a TLS handshake is a real server, running TLS,
    that this client's default verification does not trust -- downgrading to
    http:// in that case would send credentials to that server in the clear.

    Deciding this with a raw TCP connect rather than by inspecting the
    httpx/httpcore/ssl exception chain is deliberate. Reproducing this
    against a real self-signed listener showed ``httpx.ConnectError.__cause__``
    is httpcore's own ``ConnectError``, not the underlying ``ssl.SSLError`` --
    getting to the real cause takes walking multiple chain levels, and how
    many is an implementation detail of httpx/httpcore that can change
    between versions. A TCP-level check needs no exception introspection at
    all: it is agnostic to *why* the TLS handshake failed, which is exactly
    the property wanted here, since every reason it can fail means the same
    thing -- there is a TLS listener, not an empty port.
    """
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or 443
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_url_scheme(
    pc: ProductConfig,
    *,
    insecure: bool = False,
    ca_bundle: Path | None = None,
    proxy: ProxyConfig | None = None,
) -> str:
    """Fall *pc*'s URL back to ``http://`` if an inferred ``https://`` doesn't answer.

    ``vip.config._normalize_url`` defaults a scheme-less host to ``https://``
    but cannot verify reachability without a network call, which would break
    config loading's purity (it must stay network-free so, e.g., CI's
    ``--collect-only`` dry runs never dial out). This is the network-touching
    counterpart: call it once, from the first place that is actually about to
    talk to ``pc.url`` for real (an auth flow or a client constructor).

    Provenance is checked here, not by the caller: if ``pc.url_scheme_inferred``
    is ``False`` -- the user gave an explicit scheme -- this returns ``pc.url``
    unchanged without touching the network. There is deliberately no way to
    probe a URL without going through this check: an earlier version took a
    bare ``url: str`` and trusted every caller to test the flag first, which a
    type-design review flagged as a hole -- a caller that forgot, or a bare
    string with the provenance already stripped off, would silently downgrade
    a URL nobody ever marked as inferred. Taking the whole ``ProductConfig``
    makes that structurally impossible: there is no bare-string entry point
    left to misuse.

    A transport-level failure (``httpx.TransportError``) splits into cases
    that must not share a remedy:

    - The failure is a proxy failure (``httpx.ProxyError``) -- the configured
      outbound proxy could not establish the tunnel. This says nothing about
      whether the origin serves TLS, so it must NEVER trigger an http://
      downgrade: doing so would rewrite the URL to plaintext on the strength
      of a proxy hiccup and then send credentials in the clear through that
      same proxy. Keep https:// and warn about the proxy.
    - A proxy applies to this URL but the probe failed some other way -- the
      raw-socket TLS-listener tiebreak below is meaningless here (it bypasses
      the proxy, so a direct-socket "nothing is listening" verdict is about a
      path VIP will never take). When a proxy is in play we therefore do NOT
      downgrade; we keep https:// and warn, because a proxy-only network is
      exactly where a spurious downgrade does the most damage.
    - Nothing answers at all, no proxy involved (refused connection, DNS
      failure, timeout) -- "https doesn't answer" -- triggers the http://
      fallback, logged loudly so a user who meant https notices they got
      plaintext instead.
    - Something answers at the TCP level but the TLS handshake itself fails
      (untrusted/self-signed/expired certificate, protocol mismatch, ...) --
      see :func:`_tls_listener_present`. This is a *trust* problem, not a
      *reachability* problem, and downgrading here would silently send
      credentials to a real server over plaintext. This case does NOT
      downgrade: ``pc.url`` is left as https://, and a loud warning names the
      actual remedy (``[tls] insecure`` / ``[tls] ca_bundle`` in ``vip.toml``,
      or the equivalent flag on commands that have one) instead of a vague
      connection failure.

    Any actual HTTP response -- including a 5xx -- counts as "https
    answered" and is kept as-is; only a transport failure reaches either
    branch above.

    On return, ``pc.url`` holds the resolved value and ``pc.url_scheme_inferred``
    is reset to ``False`` -- resolution is a one-time transition from
    "inferred, unverified" to "settled" (settled as https in the
    trust-problem case above, not just the reachable-and-downgraded case),
    not a repeatable state. A second call on the same ``pc`` is then a plain
    attribute read, no cache lookup needed. Results are still cached per
    ``(url, insecure, ca_bundle, applicable_proxy)`` in
    ``_scheme_resolution_cache`` so a *different* ``ProductConfig`` for the same
    URL, TLS settings and proxy (e.g. a fresh instance built from the same
    ``--connect-url``) doesn't re-probe.
    """
    if not pc.url_scheme_inferred:
        return pc.url

    url = pc.url
    # The proxy that applies to this URL is part of what determines the probe's
    # outcome (a host reachable only through a proxy fails a direct probe but
    # succeeds a proxied one), so it belongs in the cache key alongside the TLS
    # settings.  ``None`` reads the ambient proxy environment, matching httpx's
    # default and the pre-existing behaviour of this bare ``httpx.get`` probe.
    proxy_map = build_proxy_map(proxy)
    applicable_proxy = proxy_for_url(url, proxy_map)
    # Userinfo-stripped form for the warning messages below; the raw
    # applicable_proxy (which may carry user:pass@) is still used for the actual
    # request and the cache key, but must never be printed to stdout/CI logs.
    safe_proxy = redact_proxy_url(applicable_proxy)
    cache_key = (url, insecure, ca_bundle, applicable_proxy)
    if cache_key in _scheme_resolution_cache:
        resolved = _scheme_resolution_cache[cache_key]
    else:
        verify = _httpx_verify_env_aware(insecure, ca_bundle)
        resolved = url
        try:
            # Route the probe through the same proxy the API clients will use,
            # and pin trust_env=False so ``applicable_proxy`` is authoritative
            # (httpx would otherwise re-read env proxies and ignore a NO_PROXY
            # bypass we deliberately resolved to None here).
            httpx.get(
                url,
                timeout=scaled(10.0),
                verify=verify,
                follow_redirects=True,
                proxy=applicable_proxy,
                trust_env=False,
            )
        except httpx.ProxyError as exc:
            # A proxy failure is not evidence about the origin's TLS. Never
            # downgrade; the raw-socket tiebreak would bypass the proxy and
            # mislead. Keep https:// and point at the proxy as the culprit.
            print(
                f">>> Warning: {url} could not be reached through the configured "
                f"proxy ({safe_proxy}): {exc}. NOT falling back to plaintext "
                f"HTTP -- the proxy, not the server's TLS, is the likely problem. "
                f"Check the proxy is reachable and permits this host, or add the "
                f"host to [proxy] no_proxy / NO_PROXY if it should be reached "
                f"directly."
            )
        except httpx.TransportError as exc:
            if applicable_proxy is not None:
                # A proxy applies but the failure wasn't a clean ProxyError
                # (e.g. a read timeout mid-tunnel). The raw-socket tiebreak
                # bypasses the proxy, so its verdict is about a path we will
                # never take -- refuse to downgrade rather than trust it.
                print(
                    f">>> Warning: {url} did not answer through the configured "
                    f"proxy ({safe_proxy}): {exc}. NOT falling back to "
                    f"plaintext HTTP while a proxy is in effect. Verify the proxy "
                    f"and target, or set an explicit http:// scheme if this host "
                    f"is genuinely plaintext."
                )
            elif _tls_listener_present(url, timeout=scaled(5.0)):
                print(
                    f">>> Warning: {url} answers on the network but its TLS "
                    f"certificate was not accepted ({exc}). NOT falling back to "
                    f"plaintext HTTP -- that would send credentials to this server "
                    f"in the clear. If this certificate is expected (e.g. "
                    f"self-signed or an internal CA), set [tls] insecure = true or "
                    f"[tls] ca_bundle in vip.toml, or pass --insecure/--ca-bundle "
                    f"where the command supports it."
                )
            else:
                resolved = "http://" + url.removeprefix("https://")
                print(
                    f">>> Warning: {url} did not answer ({exc}); falling back to plaintext "
                    f"HTTP at {resolved}. Pass an explicit http:// or https:// scheme on the "
                    f"URL to silence this."
                )
        _scheme_resolution_cache[cache_key] = resolved

    pc.url = resolved
    pc.url_scheme_inferred = False
    return resolved
