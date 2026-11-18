"""Auth-cache path, load, liveness probe, and save."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit, urlunsplit

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

# A cached session older than this is never reused, and its directory is pruned.
AUTH_CACHE_TTL_SECONDS = 4 * 3600

# Per-directory cache folders are the first 16 hex digits of a SHA-256.
_CACHE_DIR_NAME = re.compile(r"[0-9a-f]{16}")

# Cookies dropped before a storage state is written to the on-disk cache.
# Entra sets ESTSAUTHPERSISTENT even when "Stay signed in?" is answered No;
# the session ESTSAUTH cookie covers silent SSO for the cache's four-hour TTL.
_CACHE_DROPPED_COOKIES = frozenset({"ESTSAUTHPERSISTENT"})


def _user_cache_root() -> Path:
    """Per-user cache root: ``%LOCALAPPDATA%`` on Windows, else ``$XDG_CACHE_HOME`` or ``~/.cache``.

    A relative ``XDG_CACHE_HOME`` is ignored, as the XDG spec requires.  Creates nothing.
    """
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data)
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg and Path(xdg).is_absolute():
        return Path(xdg)
    return Path.home() / ".cache"


def _cwd_key(cwd: Path) -> str:
    """Name of the cache directory for *cwd*.

    The resolved path is case-folded on Windows and macOS, whose default filesystems
    ignore case, so ``~/Proj`` and ``~/proj`` share one cache.
    """
    text = os.path.normcase(str(cwd.resolve()))
    if sys.platform == "darwin":
        text = text.casefold()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def auth_cache_path() -> Path | None:
    """Path to the auth-session cache for the current invocation directory.

    Single source of truth for the cache location.  ``vip verify`` and ``vip cleanup``
    reach it through :func:`prepare_auth_cache`; they must agree, or ``cleanup`` cannot
    find the session ``verify`` just cached.

    Keyed on the *invocation* directory rather than pytest's ``config.rootpath``.
    For a repo checkout the two are the same, but for an installed VIP (``uv tool
    install posit-vip``) pytest derives rootdir from the common ancestor of the
    invocation directory and the ``site-packages`` test paths — which lands in
    ``$HOME``.  That put the cache nowhere near the user's ``vip.toml`` and made
    the two call sites read different files.

    The cache lives under the user cache directory, not in the invocation directory:
    cwd is what users zip and share, and the cache holds a live session and API key
    (#620).  This only computes the path; it touches no files and prints nothing.

    Returns ``None`` when there is no home directory (and ``XDG_CACHE_HOME`` is unset)
    or the invocation directory no longer exists.
    """
    try:
        return _user_cache_root() / "vip" / "auth" / _cwd_key(Path.cwd()) / AUTH_CACHE_FILENAME
    except (RuntimeError, OSError):
        return None


def prepare_auth_cache() -> Path | None:
    """Resolve the auth cache for a login, once per command.

    Besides :func:`auth_cache_path`, this tightens ``vip/`` and ``vip/auth/`` to
    owner-only, moves a cache an older VIP left in cwd, and deletes expired caches
    that other directories left behind.  Called by ``vip verify`` (the pytest
    controller only, not each xdist worker) and ``vip cleanup``.  Never raises.
    """
    path = auth_cache_path()
    if path is None:
        print(
            ">>> Skipping auth cache: cannot determine a home directory or the working "
            "directory; set XDG_CACHE_HOME to enable it."
        )
        return None
    base = path.parent.parent
    with contextlib.suppress(OSError):
        for directory in (base.parent, base):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory.chmod(0o700)
    with contextlib.suppress(OSError):
        _migrate_legacy_auth_cache(Path.cwd(), path)
    _prune_expired_auth_caches(base, keep=path.parent)
    return path


def _make_private_dir(directory: Path) -> None:
    """Create *directory* owner-only, tightening it if it already exists."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)


def _prune_expired_auth_caches(base: Path, keep: Path) -> None:
    """Delete cache directories under *base* whose newest file is past the TTL, never raising.

    An expired cache is never reused, so it only keeps cookies and an API key on disk.
    The key itself is removed by the stale-key sweep the next login runs on Connect.
    """
    now = time.time()
    try:
        entries = list(base.iterdir())
    except OSError:
        return
    for directory in entries:
        if directory == keep or not _CACHE_DIR_NAME.fullmatch(directory.name):
            continue
        try:
            newest = max((f.stat().st_mtime for f in directory.iterdir()), default=0.0)
            if now - newest > AUTH_CACHE_TTL_SECONDS:
                shutil.rmtree(directory)
        except OSError as exc:
            logger.debug("Could not prune expired auth cache %s: %s", directory, exc)


def _migrate_legacy_auth_cache(legacy_dir: Path, dest: Path) -> None:
    """Move the cache pair an older VIP wrote into ``legacy_dir`` to ``dest``, never raising.

    The state and meta files move together or not at all: a meta next to another
    session's state would hand out the wrong API key.  When ``dest`` already holds a
    cache, or the move fails, the legacy files are deleted instead, because a live session
    must not stay in a directory users zip and share (#620).  The orphaned Connect key is
    removed by the next login's stale-key sweep.
    """
    meta_dest = dest.with_suffix(".meta.json")
    legacy_state = legacy_dir / dest.name
    legacy_meta = legacy_dir / meta_dest.name
    try:
        if legacy_state == dest or not (legacy_state.is_file() or legacy_meta.is_file()):
            return
        move = legacy_state.is_file() and not dest.exists()
    except OSError:
        return
    if move:
        try:
            _make_private_dir(dest.parent)
            # A meta with no state belongs to no session; it must not pair with the moved one.
            meta_dest.unlink(missing_ok=True)
            shutil.move(str(legacy_state), str(dest))
            dest.chmod(0o600)
            if legacy_meta.is_file():
                shutil.move(str(legacy_meta), str(meta_dest))
                meta_dest.chmod(0o600)
            return
        except FileNotFoundError:
            # Another VIP run in this directory moved the state first; its copy stands.
            pass
        except OSError as exc:
            for moved in (dest, meta_dest):
                with contextlib.suppress(OSError):
                    moved.unlink(missing_ok=True)
            logger.warning(
                "Could not move the auth cache out of %s (%s); deleting it instead. "
                "The next run signs in again.",
                legacy_dir,
                exc,
            )
    for legacy in (legacy_state, legacy_meta):
        try:
            legacy.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove legacy auth cache %s; delete it by hand.", legacy)


def _write_private_atomic(path: Path, payload: str) -> None:
    """Write *payload* to *path* owner-only, via a temp file and rename.

    The temp file sits in the same directory so the rename is atomic, and a concurrent
    reader never sees a half-written file.
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".vip-auth-cache-")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        tmp.chmod(0o600)
        tmp.replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise


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
    cookies = httpx.Cookies()
    try:
        state = json.loads(Path(storage_state_path).read_text(encoding="utf-8"))
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
    meta_path = cache_path.with_suffix(".meta.json")
    try:
        if not cache_path.exists():
            return None
        # Check if the cache is less than 4 hours old.
        age = time.time() - cache_path.stat().st_mtime
        meta_exists = meta_path.exists()
    except OSError:
        # An inaccessible cache directory disables caching rather than aborting auth.
        return None
    if age > AUTH_CACHE_TTL_SECONDS:
        return None
    # A state with no meta is a save in progress or a half-finished one; its key is unknown.
    if not meta_exists:
        return None

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        api_key = meta.get("api_key")
        key_name = meta.get("key_name", "")
        resolved_connect_url = meta.get("connect_url", "")
        # Older caches only stored the resolved URL.  Fall back to it so a stale cache
        # still matches when the resolved and requested forms are identical.
        cached_request_connect_url = meta.get("requested_connect_url", "") or resolved_connect_url
        cached_request_workbench_url = meta.get("workbench_url", "")
    except (OSError, ValueError, AttributeError):
        return None

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


def _cacheable_storage_state(storage_state: dict) -> dict:
    """Return a copy of *storage_state* without the cookies in ``_CACHE_DROPPED_COOKIES``."""
    return {
        **storage_state,
        "cookies": [
            c
            for c in storage_state.get("cookies", [])
            if c.get("name") not in _CACHE_DROPPED_COOKIES
        ],
    }


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
    path = cache_path if cache_path is not None else auth_cache_path()
    if path is None:
        return False
    try:
        if not path.exists():
            return False
    except OSError:
        return False

    try:
        _write_private_atomic(path, json.dumps(_cacheable_storage_state(storage_state)))
        return True
    except Exception as exc:  # noqa: BLE001 -- cleanup path; never raises, see docstring
        logger.debug("Could not refresh the auth cache at %s: %s", path, exc)
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
    if session._connect_url and not session.api_key:
        print(
            ">>> Skipping auth cache: API key minting failed; next run will retry authentication."
        )
        return

    # Write the storage state to the cache location, minus long-lived IdP cookies.
    state = json.loads(session.storage_state_path.read_text(encoding="utf-8"))
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
    try:
        _make_private_dir(cache_path.parent)
        # Drop the old meta first so it never pairs with the new state.  Until the new
        # meta lands, a concurrent _load_cached_auth sees no meta and treats it as a miss.
        meta_path.unlink(missing_ok=True)
        _write_private_atomic(cache_path, json.dumps(_cacheable_storage_state(state)))
        _write_private_atomic(meta_path, json.dumps(meta))
    except (OSError, TypeError, ValueError) as exc:
        # A failed save must leave no cache: a partial pair could be reused.
        for leftover in (cache_path, meta_path):
            with contextlib.suppress(OSError):
                leftover.unlink(missing_ok=True)
        print(
            f">>> Skipping auth cache: cannot write {cache_path.parent} ({exc}); "
            "next run will re-authenticate."
        )
