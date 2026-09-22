"""Auth-cache path, load, liveness probe, and save."""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import NamedTuple

import httpx

from vip.auth.browser import InteractiveAuthSession
from vip.auth.scheme import _httpx_verify_env_aware
from vip.auth.workbench import _on_login_page
from vip.proxy import (
    ProxyConfig,
    build_proxy_map,
    proxy_for_url,
)
from vip.timeouts import scaled

logger = logging.getLogger(__name__)


AUTH_CACHE_FILENAME = ".vip-auth-cache.json"


def auth_cache_path() -> Path:
    """Path to the auth-session cache for the current invocation directory.

    Single source of truth for both call sites: ``plugin.py`` (``vip verify``)
    and ``cli.py`` (``vip cleanup --workbench-url``).  They must agree, or
    ``cleanup`` cannot find the session ``verify`` just cached.

    Keyed on the *invocation* directory rather than pytest's ``config.rootpath``.
    For a repo checkout the two are the same, but for an installed VIP (``uv tool
    install posit-vip``) pytest derives rootdir from the common ancestor of the
    invocation directory and the ``site-packages`` test paths — which lands in
    ``$HOME``.  That put the cache nowhere near the user's ``vip.toml`` and made
    the two call sites read different files.
    """
    return Path.cwd() / AUTH_CACHE_FILENAME


def _cookies_from_storage_state(storage_state_path: Path) -> httpx.Cookies:
    """Load cookies from a Playwright storage-state file, preserving their scope.

    Returns an ``httpx.Cookies`` jar with each cookie's ``domain`` and ``path``
    intact, so httpx applies ordinary cookie-matching rules when the probe fires
    and we don't hand-roll host matching.

    Scope has to survive the round trip.  ``context.storage_state()`` captures a
    whole browser context, and the auth flow deliberately visits the IdP and
    Connect as well as Workbench — so this file holds their cookies too.
    Flattening it to ``name -> value`` would fire all of them at the Workbench
    host, leaking the IdP's session cookie somewhere a browser would never send
    it, and would let two hosts using the same cookie name overwrite each other.
    That second case is the dangerous one: sending the IdP's value for a name
    Workbench also uses makes a *live* session read as dead and forces a
    pointless re-auth.

    A malformed or truncated cache yields an empty jar rather than raising: the
    probe then reads as inconclusive and the cache is reused, which is exactly
    the pre-probe behaviour.
    """
    import json

    cookies = httpx.Cookies()
    try:
        state = json.loads(Path(storage_state_path).read_text())
    except (OSError, ValueError):
        return cookies
    if not isinstance(state, dict):
        return cookies

    for cookie in state.get("cookies") or []:
        if not isinstance(cookie, dict):
            continue
        name = cookie.get("name")
        if not name:
            continue
        cookies.set(
            str(name),
            str(cookie.get("value", "")),
            domain=str(cookie.get("domain") or ""),
            path=str(cookie.get("path") or "/"),
        )
    return cookies


class _ProbeResult(NamedTuple):
    """A liveness verdict plus the evidence behind it.

    ``detail`` is quoted in the cache-miss message.  A sign-in redirect and a
    bare 401 point at different causes — an expired session versus something
    stripping cookies in front of Workbench — so the message has to say which
    one was seen rather than assume the redirect.
    """

    is_live: bool | None
    detail: str = ""


def _cached_workbench_session_is_live(
    workbench_url: str,
    cookies: httpx.Cookies,
    *,
    insecure: bool = False,
    ca_bundle: Path | None = None,
    transport: httpx.BaseTransport | None = None,
    proxy: ProxyConfig | None = None,
) -> _ProbeResult:
    """Report whether *cookies* still authenticate Workbench at *workbench_url*.

    ``is_live`` is ``True`` when the session lands on the dashboard, ``False`` on
    positive evidence that it is dead (a redirect to the sign-in page, or a bare
    401/403 from configs that do not redirect), and ``None`` when the probe could
    not reach a verdict.

    ``None`` is deliberately distinct from ``False``.  An unreachable deployment
    is not a dead session: treating a transport error as dead would discard a
    perfectly good cache, trigger an interactive re-auth that cannot succeed
    either, and bury the real reachability error behind an auth-shaped one.
    """
    verify = _httpx_verify_env_aware(insecure, ca_bundle)
    # Route the liveness probe through the same proxy the clients use, but only
    # when no explicit transport was injected (a test's MockTransport must not
    # get a proxy mount layered on top). build_proxy_map already consulted the
    # environment where appropriate, so trust_env=False makes that resolved
    # per-URL proxy authoritative (and is moot when a transport is injected,
    # since httpx ignores env proxies whenever a transport is supplied).
    probe_proxy = (
        None if transport is not None else proxy_for_url(workbench_url, build_proxy_map(proxy))
    )
    try:
        with httpx.Client(
            timeout=scaled(10.0),
            verify=verify,
            follow_redirects=True,
            cookies=cookies,
            transport=transport,
            proxy=probe_proxy,
            trust_env=False,
        ) as client:
            response = client.get(workbench_url)
    except httpx.HTTPError as exc:
        return _ProbeResult(None, f"could not reach Workbench: {exc}")

    if response.status_code in (401, 403):
        return _ProbeResult(False, f"Workbench answered {response.status_code}")
    if _on_login_page(str(response.url)):
        return _ProbeResult(False, f"the request landed on the sign-in page at {response.url}")
    return _ProbeResult(True)


def _load_cached_auth(
    cache_path: Path,
    requested_connect_url: str | None = None,
    requested_workbench_url: str | None = None,
    *,
    insecure: bool = False,
    ca_bundle: Path | None = None,
    proxy: ProxyConfig | None = None,
) -> InteractiveAuthSession | None:
    """Load a cached auth session if it exists, is recent, and still works.

    The cache lives at :func:`auth_cache_path` — one slot per invocation
    directory, not per site.  If the caller is now targeting a different Connect
    or Workbench URL than the one the cache was minted against, reusing the saved
    storage state would silently send the wrong session cookies (and the wrong
    API key) to the new site.  We treat any URL mismatch as a cache miss so the
    next run re-authenticates cleanly.

    The four-hour TTL alone is not enough: the saved IdP session can die well
    inside it (expiry, an admin revoking it, a password change).  Nothing on this
    path ran :func:`_authenticate_workbench`, so ``workbench_auth_error`` stayed
    ``None`` and every Workbench test skipped with a message that named no cause.
    So when Workbench is requested we probe it before trusting the cache.
    """
    if not cache_path.exists():
        return None

    import json

    # Check if the cache is less than 4 hours old.
    age = time.time() - cache_path.stat().st_mtime
    if age > 4 * 3600:
        return None

    # Read the companion metadata file if it exists.
    meta_path = cache_path.with_suffix(".meta.json")
    api_key = None
    key_name = ""
    resolved_connect_url = ""
    cached_request_connect_url = ""
    cached_request_workbench_url = ""
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            api_key = meta.get("api_key")
            key_name = meta.get("key_name", "")
            resolved_connect_url = meta.get("connect_url", "")
            # Older caches (pre-fix) only stored the resolved URL.  Fall
            # back to it so a stale cache still matches when the
            # resolved and requested forms are identical (no sub-path
            # rewrite happened).
            cached_request_connect_url = (
                meta.get("requested_connect_url", "") or resolved_connect_url
            )
            cached_request_workbench_url = meta.get("workbench_url", "")
        except (OSError, ValueError, AttributeError):
            pass

    # Match against the *requested* Connect URL so that
    # ``_resolve_connect_api_base`` rewriting the dashboard URL to a
    # different API base doesn't force a cache miss on every run.
    if not _cached_urls_match(
        cached_request_connect_url,
        cached_request_workbench_url,
        requested_connect_url,
        requested_workbench_url,
    ):
        print(
            ">>> Ignoring cached auth session: requested URLs differ from cached "
            f"(cached connect={cached_request_connect_url or '∅'}, "
            f"workbench={cached_request_workbench_url or '∅'}; "
            f"requested connect={requested_connect_url or '∅'}, "
            f"workbench={requested_workbench_url or '∅'})."
        )
        return None

    # Liveness probe: only when Workbench is actually requested, so Connect-only
    # runs pay nothing for it.
    if requested_workbench_url:
        probe = _cached_workbench_session_is_live(
            requested_workbench_url,
            _cookies_from_storage_state(cache_path),
            insecure=insecure,
            ca_bundle=ca_bundle,
            proxy=proxy,
        )
        if probe.is_live is False:
            print(
                ">>> Ignoring cached auth session: the saved browser session no longer "
                f"authenticates Workbench at {requested_workbench_url} "
                f"({probe.detail}). Re-authenticating."
            )
            return None

    print(f">>> Reusing cached auth session from {cache_path}")
    return InteractiveAuthSession(
        storage_state_path=cache_path,
        api_key=api_key,
        key_name=key_name,
        _connect_url=resolved_connect_url,
        _requested_connect_url=cached_request_connect_url,
        _workbench_url=cached_request_workbench_url,
        _tmpdir="",
        _cache_path=cache_path,
    )


def _normalize_url(url: str | None) -> str:
    """Normalize a product URL for cache-key comparison.

    Per RFC 3986 the scheme and host are case-insensitive but the path
    is case-sensitive — Connect can be served at ``/Dashboard`` and
    ``/dashboard`` as distinct routes when a sub-path mount is used.
    Lowercasing the whole string (the prior behaviour) collapsed those
    into the same cache slot and could reuse storage state minted
    against a different deployment path.

    We lowercase only the scheme and netloc, preserve path case, strip
    a single trailing ``/`` from the path, and drop query/fragment
    (auth cache keying off ``?foo=bar`` would be surprising).
    """
    if not url:
        return ""

    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    # Strip at most one trailing slash so ``/app`` and ``/app/`` match,
    # but ``/app/`` and ``/app//`` remain distinct (some deployments
    # route them to different handlers).  ``removesuffix`` also turns a
    # bare ``/`` into ``""`` so a configured-without-trailing-slash URL
    # matches the same host with ``/`` appended.
    path = parts.path.removesuffix("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def _cached_urls_match(
    cached_connect: str,
    cached_workbench: str,
    requested_connect: str | None,
    requested_workbench: str | None,
) -> bool:
    """True when the cache's recorded URLs match the requested ones.

    A blank cached URL is only acceptable when the caller also did not
    request that product — a cache minted with Connect-only cannot serve
    a later run that now also wants Workbench (storage state would lack
    Workbench cookies).
    """
    return _normalize_url(cached_connect) == _normalize_url(requested_connect) and (
        _normalize_url(cached_workbench) == _normalize_url(requested_workbench)
    )


def refresh_auth_cache_from_storage_state(
    storage_state: dict, cache_path: Path | None = None
) -> bool:
    """Rewrite the cached storage state from a live browser context.

    A scenario that ends the shared Workbench session (``test_workbench_signout``)
    can mint a fresh one in its browser context, but the cache on disk still
    holds the cookies the sign-out killed.  The next ``vip verify`` then probes
    that cache, finds it dead, and drops into an interactive re-auth -- opening a
    browser at the user on every run.  Writing the restored context's state back
    keeps the cache usable.

    Only refreshes a cache that already exists.  Absent means no
    ``--interactive-auth`` run put one there (a password deployment, say), and
    creating one here would leave a storage state with no companion
    ``.meta.json`` for :func:`_load_cached_auth` to match URLs against.

    The write is atomic (temp file in the same directory, then rename) so a
    concurrent xdist worker reading the cache never sees a half-written file,
    and the replacement carries the same owner-only permissions as the original
    -- it holds live session cookies.

    Returns True when the cache was refreshed.  Never raises: this runs on a
    cleanup path, where failing loudly would mask the test's own result.
    """
    import json

    path = cache_path if cache_path is not None else auth_cache_path()
    if not path.exists():
        return False

    tmp: Path | None = None
    try:
        payload = json.dumps(storage_state)
        # Same directory so the rename stays on one filesystem (and therefore
        # atomic); mkstemp creates it 0600 already.
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".vip-auth-cache-")
        tmp = Path(tmp_name)
        with os.fdopen(fd, "w") as handle:
            handle.write(payload)
        tmp.chmod(0o600)
        tmp.replace(path)
        return True
    except Exception as exc:  # noqa: BLE001 -- cleanup path; never raises, see docstring
        logger.debug("Could not refresh the auth cache at %s: %s", path, exc)
        if tmp is not None and tmp.exists():
            with contextlib.suppress(OSError):
                tmp.unlink()
        return False


def _save_auth_cache(session: InteractiveAuthSession, cache_path: Path) -> None:
    """Save auth session metadata alongside the storage state.

    Skips the write when Connect was configured but key minting failed
    (``_connect_url`` set, ``api_key`` falsy).  Caching that state
    short-circuits subsequent runs via :func:`_load_cached_auth` and
    suppresses the retry — so a single transient mint failure would
    poison the cache for four hours and hide the specific warning that
    explains *why* minting failed.
    """
    import json
    import shutil as _shutil

    if session._connect_url and not session.api_key:
        print(
            ">>> Skipping auth cache: API key minting failed; next run will retry authentication."
        )
        return

    # Copy storage state to the cache location.
    _shutil.copy2(session.storage_state_path, cache_path)
    cache_path.chmod(0o600)

    # Write companion metadata.  ``connect_url`` keeps the resolved
    # form (used for API key cleanup); ``requested_connect_url`` keeps
    # the pre-resolve form for cache-key matching.  Older releases only
    # wrote ``connect_url`` — :func:`_load_cached_auth` handles that
    # case by falling back to it when ``requested_connect_url`` is
    # missing.
    meta_path = cache_path.with_suffix(".meta.json")
    meta = {
        "api_key": session.api_key,
        "key_name": session.key_name,
        "connect_url": session._connect_url,
        "requested_connect_url": session._requested_connect_url or session._connect_url,
        "workbench_url": session._workbench_url,
    }
    meta_path.write_text(json.dumps(meta))
    meta_path.chmod(0o600)
