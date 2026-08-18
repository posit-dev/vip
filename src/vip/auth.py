"""Interactive browser authentication for OIDC providers.

Opens a headed Chromium browser for the user to complete an OIDC login
flow, mints a temporary Connect API key by calling the Connect REST API
with the browser's session cookies, saves the browser storage state, then
closes the browser before tests start.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import ssl
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import httpx
from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    Page,
    sync_playwright,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from vip.proxy import (
    ProxyConfig,
    build_proxy_map,
    chromium_launch_args,
    playwright_proxy,
    proxy_for_url,
    redact_proxy_url,
    verify_with_env_ca,
)
from vip.timeouts import scaled

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from vip.config import ProductConfig


class AuthConfigError(ValueError):
    """Raised for user-facing authentication configuration errors."""


# Prefix for VIP-managed API keys.  A timestamp is appended per run.
_KEY_NAME_PREFIX = "_vip_interactive_"

# Orphan keys younger than this are left alone so a concurrent ``vip verify``
# run does not have its freshly-minted key yanked out from under it.  Cleanup
# is for keys whose process crashed before running ``cleanup()``; anything
# recent enough to still belong to a live run is out of scope.
_ORPHAN_MIN_AGE_SECONDS = 3600


# Substrings that indicate the chromium launch failed because host-level
# system libraries (libatk, libgbm, libasound, ...) are not installed.  See
# https://github.com/posit-dev/vip/issues/169.
_MISSING_DEPS_SIGNALS = (
    "host system is missing dependencies",
    "error while loading shared libraries",
)

_MISSING_DEPS_HINT = (
    "Chromium could not launch because required system libraries are missing "
    "on this host. Install them with:\n\n"
    "    uv run vip install"
)

# Substring of Playwright's own error when a headed browser is launched with
# no display (e.g. --interactive-auth run directly, over SSH, on a headless
# Connect, Workbench, or Package Manager server). See
# https://github.com/posit-dev/vip/issues/588.
_NO_DISPLAY_SIGNALS = ("headed browser without having a xserver running",)

_NO_DISPLAY_HINT = (
    "--interactive-auth opens a visible browser window, so it needs a display "
    "and must run from your own workstation or CI runner -- not a headless "
    "Connect, Workbench, or Package Manager server. From a headless host, use "
    "--headless-auth (or --api-auth) instead."
)


def _launch_chromium(
    pw,
    *,
    headless: bool,
    proxy: dict[str, str] | None = None,
    args: list[str] | None = None,
):
    """Launch Chromium via Playwright, turning missing-system-deps and
    no-display errors into a clear :class:`AuthConfigError` with a
    remediation command.

    When *proxy* is a Playwright proxy dict (``{"server": ..., "bypass": ...}``,
    from :func:`vip.proxy.playwright_proxy`), it is passed to ``launch`` so the
    browser login traverses the same proxy as VIP's httpx egress. Chromium's own
    env-proxy detection is platform-dependent; setting it explicitly makes the
    browser and API paths agree. ``None`` launches exactly as before.

    *args* carries extra Chromium switches from
    :func:`vip.proxy.chromium_launch_args` -- specifically ``--no-proxy-server``
    when the user explicitly disabled proxying, which ``proxy=None`` alone does
    not achieve (Chromium falls back to its own env/system detection).

    Other Playwright errors (e.g. an already-running browser) propagate
    unchanged so callers can surface them as needed.
    """
    launch_kwargs: dict = {"headless": headless}
    if proxy is not None:
        launch_kwargs["proxy"] = proxy
    if args:
        launch_kwargs["args"] = args
    try:
        return pw.chromium.launch(**launch_kwargs)
    except PlaywrightError as exc:
        text = str(exc).lower()
        if any(signal in text for signal in _MISSING_DEPS_SIGNALS):
            raise AuthConfigError(_MISSING_DEPS_HINT) from exc
        if any(signal in text for signal in _NO_DISPLAY_SIGNALS):
            raise AuthConfigError(_NO_DISPLAY_HINT) from exc
        raise


@dataclass
class InteractiveAuthSession:
    """Result of an interactive OIDC authentication flow.

    Holds the saved browser storage state (for Playwright tests) and a
    minted Connect API key (for httpx API tests).  Call ``cleanup()``
    after the test session to delete the temporary API key.
    """

    storage_state_path: Path
    api_key: str | None = None
    key_name: str = ""
    workbench_auth_error: str | None = None

    _connect_url: str = field(default="", repr=False)
    # The Connect URL as originally supplied by the caller, before
    # ``_resolve_connect_api_base`` may have rewritten it to a separate
    # dashboard/API base.  ``_connect_url`` continues to hold the
    # resolved value so API key cleanup hits the right endpoint, while
    # cache-key matching uses this requested form so a stable
    # configuration cache-hits cleanly even when the dashboard sits at
    # a sub-path that resolves to a different API base.
    _requested_connect_url: str = field(default="", repr=False)
    _workbench_url: str = field(default="", repr=False)
    _tmpdir: str = field(default="", repr=False)
    _cache_path: Path | None = field(default=None, repr=False)
    _insecure: bool = field(default=False, repr=False)
    _ca_bundle: Path | None = field(default=None, repr=False)
    _proxy: ProxyConfig | None = field(default=None, repr=False)

    def load_cookies(self) -> httpx.Cookies:
        """Build an httpx cookie jar from the saved Playwright storage state.

        The Playwright storage-state JSON has the form::

            {"cookies": [{"name": ..., "value": ..., "domain": ..., "path": ...}, ...], ...}

        Each cookie's ``domain`` and ``path`` are preserved so a parent-domain
        wildcard cookie (e.g. ``.current.posit.team``) routes correctly to
        subdomains like ``pub.current.posit.team`` when the jar is attached to
        an httpx client.

        All cookies are loaded without filtering by hostname — httpx handles
        routing by domain/path at request time.

        Returns an empty :class:`httpx.Cookies` when the storage-state file is
        missing, unreadable, or unparseable (graceful degradation for the
        config-API-key path where no interactive auth ran).
        """
        import json as _json

        cookies = httpx.Cookies()
        try:
            raw = _json.loads(self.storage_state_path.read_text())
            if not isinstance(raw, dict):
                return cookies
            for c in raw.get("cookies", []):
                if not isinstance(c, dict):
                    continue
                name = c.get("name", "")
                if not name:
                    continue
                value = c.get("value", "")
                domain = c.get("domain", "")
                path = c.get("path", "/")
                cookies.set(name, value, domain=domain, path=path)
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        return cookies

    def _cache_references_this_key(self) -> bool:
        """True when the on-disk cache still points at our ``api_key``.

        If so, deleting the key at cleanup would break the next run's
        cache hit (it would load a dead key and 401 on every request).
        We'd rather leave the key alive; ``_delete_stale_vip_keys`` at
        the next real mint reaps anything older than the orphan window.

        Both the storage-state file *and* the companion meta file must
        exist *and be valid JSON*: a stale meta without the state file,
        or a corrupted state file Playwright can't load, is not
        reachable as a cache hit, so our key isn't truly referenced and
        should be deleted rather than orphaned.
        """
        if not self._cache_path or not self.api_key:
            return False
        if not self._cache_path.exists():
            return False
        meta_path = self._cache_path.with_suffix(".meta.json")
        if not meta_path.exists():
            return False
        try:
            import json

            # Validate the cache state file is parseable JSON.  A corrupt
            # state file would make Playwright's ``storage_state=`` load
            # fail on the next run; treating it as a live reference would
            # leak the API key until the next mint-time sweep.
            json.loads(self._cache_path.read_text())
            meta = json.loads(meta_path.read_text())
        except (OSError, ValueError):
            return False
        return meta.get("api_key") == self.api_key

    def cleanup(self) -> None:
        """Delete the minted API key and remove the temp directory."""
        if self.api_key and self._connect_url and not self._cache_references_this_key():
            try:
                _delete_api_key(
                    self._connect_url,
                    self.api_key,
                    self.key_name,
                    insecure=self._insecure,
                    ca_bundle=self._ca_bundle,
                    proxy=self._proxy,
                )
            except Exception as exc:
                print(f">>> Warning: Could not delete API key: {exc}")

        if self._tmpdir and os.path.isdir(self._tmpdir):
            shutil.rmtree(self._tmpdir, ignore_errors=True)


@contextmanager
def authenticated_page(
    session: InteractiveAuthSession,
    *,
    insecure: bool = False,
    ca_bundle: Path | None = None,
    proxy: ProxyConfig | None = None,
) -> Iterator[Page]:
    """Open a headless, authenticated Playwright page from a cached auth session.

    Loads *session*'s saved storage state into a fresh headless browser
    context, so callers outside of a pytest run (e.g. ``vip cleanup
    --workbench-url``, see :func:`vip.cli.run_cleanup`) can drive a product's
    UI using the same login a prior ``vip verify`` already completed, without
    prompting for credentials again.

    Honors *insecure*/*ca_bundle* the same way :func:`start_headless_auth`
    does (TLS verification skip, ``NODE_EXTRA_CA_CERTS`` for a custom CA).
    Closes the page's context, the browser, and the Playwright driver on
    exit, restoring ``NODE_EXTRA_CA_CERTS`` to its previous value, regardless
    of how the ``with`` block exits.
    """
    pw = None
    browser = None
    _prev_node_ca = os.environ.get("NODE_EXTRA_CA_CERTS")
    if ca_bundle is not None:
        os.environ["NODE_EXTRA_CA_CERTS"] = str(ca_bundle)
    # The page this opens drives the Workbench UI, so resolve the proxy for that
    # URL specifically -- an http:// Workbench must take the http proxy, not
    # whatever an https URL would have selected.
    pw_proxy = playwright_proxy(build_proxy_map(proxy), session._workbench_url or None)
    pw_args = chromium_launch_args(proxy)
    try:
        pw = sync_playwright().start()
        browser = _launch_chromium(pw, headless=True, proxy=pw_proxy, args=pw_args)
        context = browser.new_context(
            storage_state=str(session.storage_state_path),
            ignore_https_errors=insecure,
        )
        try:
            yield context.new_page()
        finally:
            try:
                context.close()
            except Exception:
                pass
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if pw is not None:
            try:
                pw.stop()
            except Exception:
                pass
        if ca_bundle is not None:
            if _prev_node_ca is None:
                os.environ.pop("NODE_EXTRA_CA_CERTS", None)
            else:
                os.environ["NODE_EXTRA_CA_CERTS"] = _prev_node_ca


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
        except Exception:
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
    (auth cache keying off ``?foo=bar`` would be surprising)."""
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
    Workbench cookies)."""
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
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        return True
    except Exception as exc:
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
    os.chmod(cache_path, 0o600)

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
    os.chmod(meta_path, 0o600)


def _resolve_str_if_inferred(
    url: str | None,
    inferred: bool,
    *,
    insecure: bool,
    ca_bundle: Path | None,
    proxy: ProxyConfig | None = None,
) -> str | None:
    """Resolve a bare url string through ``resolve_url_scheme``'s provenance check.

    ``start_interactive_auth``/``start_headless_auth`` receive ``connect_url``/
    ``workbench_url`` as plain strings plus a separate ``*_scheme_inferred``
    bool -- that's the shape ``vip.plugin`` already has to pass across the
    ``VIPConfig`` -> CLI-function boundary -- rather than a ``ProductConfig``
    object. ``resolve_url_scheme`` only takes a ``ProductConfig`` (see its
    docstring for why), so this builds a throwaway one to carry *inferred*
    across, calls ``resolve_url_scheme``, and returns the resolved string.
    """
    if not url:
        return url
    from vip.config import ProductConfig

    # ProductConfig.__post_init__ runs _normalize_url on construction, but
    # *url* here has already been normalized upstream (it always has an
    # explicit http:// or https:// prefix by the time it reaches this
    # function) -- so the inferred flag __post_init__ computes is always
    # False and meaningless. Overwrite it with the caller's *inferred*,
    # which is the actual, authoritative provenance carried separately
    # alongside the string. This overwrite-right-after-construction is a
    # known wart, not a bug: the clean fix is changing start_interactive_auth/
    # start_headless_auth to take ProductConfig objects directly instead of
    # a string + a separate bool, which would touch ~15 call sites across
    # test_auth.py plus plugin.py/cli.py -- out of scope for this bug fix.
    pc = ProductConfig(url=url)
    pc.url_scheme_inferred = inferred
    return resolve_url_scheme(pc, insecure=insecure, ca_bundle=ca_bundle, proxy=proxy)


def start_interactive_auth(
    connect_url: str | None = None,
    workbench_url: str | None = None,
    cache_path: Path | None = None,
    insecure: bool = False,
    ca_bundle: Path | None = None,
    connect_url_scheme_inferred: bool = False,
    workbench_url_scheme_inferred: bool = False,
    proxy: ProxyConfig | None = None,
) -> InteractiveAuthSession:
    """Launch a headed browser, authenticate via OIDC, and optionally
    mint a Connect API key through the UI.

    At least one of *connect_url* or *workbench_url* must be provided.

    When *connect_url* is given, the browser opens Connect's login page
    and attempts to mint a temporary API key.  If *workbench_url* is
    also provided, the browser visits Workbench afterward so the saved
    storage state contains session cookies for both products (SSO handles
    the second authentication automatically).

    When only *workbench_url* is given, the browser opens Workbench
    directly.  No Connect API key is minted.

    The browser is closed before this function returns.  pytest-playwright
    creates its own browser instance using the saved storage state.

    When *insecure* is ``True``, Playwright ignores TLS certificate errors.
    When *ca_bundle* is set, the path is exported as ``NODE_EXTRA_CA_CERTS``
    before launching Chromium so it trusts a custom CA (Chromium-level trust
    only; this does not update the OS certificate store).

    *connect_url_scheme_inferred* / *workbench_url_scheme_inferred* mark a URL
    whose ``https://`` scheme was inferred by ``vip.config._normalize_url``
    rather than given explicitly (``ProductConfig.url_scheme_inferred``).
    When set, :func:`resolve_url_scheme` probes the URL and falls back to
    ``http://`` if https doesn't answer, before it's used for anything.
    """
    if not connect_url and not workbench_url:
        raise ValueError(
            "--interactive-auth requires at least one product URL (Connect or Workbench)"
        )

    # Check for a valid cached session.
    if cache_path:
        cached = _load_cached_auth(
            cache_path,
            connect_url,
            workbench_url,
            insecure=insecure,
            ca_bundle=ca_bundle,
            proxy=proxy,
        )
        if cached is not None:
            return cached

    connect_url = _resolve_str_if_inferred(
        connect_url,
        connect_url_scheme_inferred,
        insecure=insecure,
        ca_bundle=ca_bundle,
        proxy=proxy,
    )
    workbench_url = _resolve_str_if_inferred(
        workbench_url,
        workbench_url_scheme_inferred,
        insecure=insecure,
        ca_bundle=ca_bundle,
        proxy=proxy,
    )

    # Determine the primary login target.
    primary_url = connect_url or workbench_url
    assert primary_url is not None  # guaranteed by the check above
    login_path = "/__login__" if connect_url else ""

    tmpdir = tempfile.mkdtemp(prefix="vip-auth-")
    storage_state_path = Path(tmpdir) / "vip-auth-state.json"
    os.chmod(tmpdir, 0o700)

    key_name = f"{_KEY_NAME_PREFIX}{int(time.time())}"

    # Route the browser login through the same proxy as VIP's httpx egress, so
    # the interactive login does not silently take a different network path than
    # the API-key mint and the product clients (Chromium's implicit env-proxy
    # detection is platform-dependent; this makes it explicit and consistent).
    # Resolved for ``primary_url`` -- the URL this browser is about to navigate --
    # so an http:// product selects the http proxy rather than the https one.
    pw_proxy = playwright_proxy(build_proxy_map(proxy), primary_url)
    pw_args = chromium_launch_args(proxy)

    pw = None
    browser = None
    _prev_node_ca = os.environ.get("NODE_EXTRA_CA_CERTS")
    if ca_bundle is not None:
        os.environ["NODE_EXTRA_CA_CERTS"] = str(ca_bundle)
    try:
        pw = sync_playwright().start()
        browser = _launch_chromium(pw, headless=False, proxy=pw_proxy, args=pw_args)
        context = browser.new_context(ignore_https_errors=insecure)
        page = context.new_page()

        page.goto(f"{primary_url}{login_path}")

        print(f"\n>>> A browser window has opened at {primary_url}")
        print(">>> Please log in through your identity provider.")
        print(">>> The browser will close automatically after login.\n")

        # Poll until login completes
        base = primary_url.rstrip("/")
        deadline = time.monotonic() + scaled(300)
        login_completed = False

        # Login detection: for Connect check we left /__login__,
        # for Workbench check we're no longer on a login/auth page.
        while time.monotonic() < deadline:
            try:
                url = page.url
            except Exception:
                break
            if connect_url:
                if base in url and "/__login__" not in url:
                    login_completed = True
                    break
            else:
                # For Workbench, login is complete when we're on the
                # homepage (no login/auth keywords in the URL).
                lower = url.lower()
                at_login = any(kw in lower for kw in ("sign-in", "login", "auth"))
                if base.rstrip("/").lower() in lower and not at_login:
                    login_completed = True
                    break
            try:
                page.wait_for_timeout(500)
            except Exception:
                break

        if not login_completed:
            raise RuntimeError(
                "Login did not complete within 5 minutes. "
                "Please rerun and complete authentication in the browser window."
            )

        # Mint Connect API key only if Connect is configured.  Keep the
        # caller's original URL for cache-key matching; the rewritten
        # form is what we actually mint and clean up against.
        api_key = None
        requested_connect_url = connect_url or ""
        if connect_url:
            connect_url = _resolve_connect_api_base(
                connect_url, insecure=insecure, ca_bundle=ca_bundle, proxy=proxy
            )
            api_key = _create_api_key_via_session(
                page, connect_url, key_name, insecure=insecure, ca_bundle=ca_bundle, proxy=proxy
            )

        # Visit Workbench so the storage state includes its session cookies.
        workbench_auth_error: str | None = None
        if workbench_url and connect_url:
            workbench_auth_error = _authenticate_workbench(page, workbench_url)

        context.storage_state(path=str(storage_state_path))

        session = InteractiveAuthSession(
            storage_state_path=storage_state_path,
            api_key=api_key,
            key_name=key_name,
            workbench_auth_error=workbench_auth_error,
            _connect_url=connect_url or "",
            _requested_connect_url=requested_connect_url,
            _workbench_url=workbench_url or "",
            _tmpdir=tmpdir,
            _cache_path=cache_path,
            _insecure=insecure,
            _ca_bundle=ca_bundle,
            _proxy=proxy,
        )

        # Cache the session for reuse across runs.
        if cache_path:
            _save_auth_cache(session, cache_path)

        return session
    except Exception:
        if tmpdir and os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if pw is not None:
            try:
                pw.stop()
            except Exception:
                pass
        # Restore NODE_EXTRA_CA_CERTS to its previous value so subsequent
        # auth calls (or test runs) are not silently affected.
        if ca_bundle is not None:
            if _prev_node_ca is None:
                os.environ.pop("NODE_EXTRA_CA_CERTS", None)
            else:
                os.environ["NODE_EXTRA_CA_CERTS"] = _prev_node_ca


_IDP_PROVIDERS = frozenset({"oidc", "saml", "oauth2"})


def start_headless_auth(
    connect_url: str | None = None,
    workbench_url: str | None = None,
    idp: str = "",
    provider: str = "password",
    username: str = "",
    password: str = "",
    cache_path: Path | None = None,
    verbose: bool = False,
    insecure: bool = False,
    ca_bundle: Path | None = None,
    connect_url_scheme_inferred: bool = False,
    workbench_url_scheme_inferred: bool = False,
    proxy: ProxyConfig | None = None,
) -> InteractiveAuthSession:
    """Launch a headless browser, automate OIDC login, and optionally
    mint a Connect API key through the UI.

    This is the headless counterpart to ``start_interactive_auth()``.
    Instead of showing a browser window for manual login, it fills the
    IdP login form automatically and prompts via the terminal for MFA
    codes when needed.

    At least one of *connect_url* or *workbench_url* must be provided.
    The *idp* parameter selects which form automation strategy to use
    (e.g. ``"keycloak"``, ``"okta"``, ``"snowflake"``).

    When *insecure* is ``True``, Playwright ignores TLS certificate errors.
    When *ca_bundle* is set, the path is exported as ``NODE_EXTRA_CA_CERTS``
    before launching Chromium so it trusts a custom CA (Chromium-level trust
    only; this does not update the OS certificate store).

    *connect_url_scheme_inferred* / *workbench_url_scheme_inferred*: see
    ``start_interactive_auth``.
    """
    import vip.idp as _idp_mod

    _idp_mod._verbose = verbose

    if not connect_url and not workbench_url:
        raise AuthConfigError(
            "--headless-auth requires at least one product URL (Connect or Workbench)"
        )

    # Check for a valid cached session before validating credentials/idp,
    # so a warm cache works even when env vars are not set.
    if cache_path:
        cached = _load_cached_auth(
            cache_path,
            connect_url,
            workbench_url,
            insecure=insecure,
            ca_bundle=ca_bundle,
            proxy=proxy,
        )
        if cached is not None:
            return cached

    if not username or not password:
        raise AuthConfigError(
            "--headless-auth requires test credentials. "
            "Set VIP_TEST_USERNAME and VIP_TEST_PASSWORD."
        )

    # Validate VIP_TEST_TOTP_SECRET (if set) before launching Playwright
    # so a bad seed fails fast with a clear error.
    from vip import totp

    totp_secret = os.environ.get(totp.ENV_VAR, "").strip()
    if totp_secret:
        totp.validate_secret(totp_secret)

    # Choose login flow based on auth provider, not idp presence.
    # OIDC/SAML/OAuth2 → IdP form automation; password/LDAP → native form.
    uses_idp = provider.strip().lower() in _IDP_PROVIDERS
    fill_login = None
    if uses_idp:
        from vip.idp import SUPPORTED_IDPS, get_idp_strategy

        if not idp:
            supported = ", ".join(f'"{name}"' for name in sorted(SUPPORTED_IDPS))
            raise AuthConfigError(
                f"--headless-auth with provider={provider!r} requires"
                f" [auth] idp in vip.toml (supported: {supported})"
            )

        fill_login = get_idp_strategy(idp)

    # Resolve inferred https:// schemes now, after every fail-fast validation
    # above and right before anything (Playwright or httpx) actually talks to
    # the URLs, so a config error never pays for a network probe it doesn't need.
    connect_url = _resolve_str_if_inferred(
        connect_url,
        connect_url_scheme_inferred,
        insecure=insecure,
        ca_bundle=ca_bundle,
        proxy=proxy,
    )
    workbench_url = _resolve_str_if_inferred(
        workbench_url,
        workbench_url_scheme_inferred,
        insecure=insecure,
        ca_bundle=ca_bundle,
        proxy=proxy,
    )

    # Determine the primary login target.
    primary_url = connect_url or workbench_url
    assert primary_url is not None
    login_path = "/__login__" if connect_url else ""

    tmpdir = tempfile.mkdtemp(prefix="vip-auth-")
    storage_state_path = Path(tmpdir) / "vip-auth-state.json"
    os.chmod(tmpdir, 0o700)

    key_name = f"{_KEY_NAME_PREFIX}{int(time.time())}"

    # Same proxy as VIP's httpx egress, so the headless login shares the network
    # path of the mint and product clients rather than Chromium's implicit one.
    # Resolved for the URL this browser will navigate (see start_interactive_auth).
    pw_proxy = playwright_proxy(build_proxy_map(proxy), primary_url)
    pw_args = chromium_launch_args(proxy)

    pw = None
    browser = None
    _prev_node_ca = os.environ.get("NODE_EXTRA_CA_CERTS")
    if ca_bundle is not None:
        os.environ["NODE_EXTRA_CA_CERTS"] = str(ca_bundle)
    try:
        pw = sync_playwright().start()
        browser = _launch_chromium(pw, headless=True, proxy=pw_proxy, args=pw_args)
        context = browser.new_context(ignore_https_errors=insecure)
        page = context.new_page()

        from vip.idp import _log_verbose, _sanitize_url

        target = f"{primary_url}{login_path}"
        print(f"\n>>> Headless auth: authenticating to {primary_url} ...", flush=True)
        try:
            page.goto(target)
            page.wait_for_load_state("domcontentloaded")
            _log_verbose(f">>> Page loaded, URL: {_sanitize_url(page.url)}")

            if fill_login:
                # OIDC/SAML: navigate to IdP and automate its login form.
                _navigate_to_idp(page, primary_url)
                _log_verbose(f">>> At IdP login page: {_sanitize_url(page.url)}")
                fill_login(page, username, password)
            else:
                # Password/LDAP: fill the product's native login form directly.
                _fill_product_login(page, username, password)

            # Wait for redirect back to the product.
            _wait_for_product_redirect(page, primary_url)
        except PlaywrightTimeoutError as exc:
            raise AuthConfigError(
                "Headless auth timed out during login. "
                "Check the product URL and IdP configuration, or rerun with "
                "--verbose for details."
            ) from exc
        except PlaywrightError as exc:
            raise AuthConfigError(
                f"Headless auth failed during login: {exc}. Rerun with --verbose for details."
            ) from exc
        print(">>> Authentication complete.")

        # Mint Connect API key only if Connect is configured.  Keep the
        # caller's original URL for cache-key matching; the rewritten
        # form is what we actually mint and clean up against.
        api_key = None
        requested_connect_url = connect_url or ""
        if connect_url:
            connect_url = _resolve_connect_api_base(
                connect_url, insecure=insecure, ca_bundle=ca_bundle, proxy=proxy
            )
            api_key = _create_api_key_via_session(
                page, connect_url, key_name, insecure=insecure, ca_bundle=ca_bundle, proxy=proxy
            )

        # Visit Workbench so the storage state includes its session cookies.
        workbench_auth_error: str | None = None
        if workbench_url and connect_url:
            workbench_auth_error = _authenticate_workbench(page, workbench_url)

        context.storage_state(path=str(storage_state_path))

        session = InteractiveAuthSession(
            storage_state_path=storage_state_path,
            api_key=api_key,
            key_name=key_name,
            workbench_auth_error=workbench_auth_error,
            _connect_url=connect_url or "",
            _requested_connect_url=requested_connect_url,
            _workbench_url=workbench_url or "",
            _tmpdir=tmpdir,
            _cache_path=cache_path,
            _insecure=insecure,
            _ca_bundle=ca_bundle,
            _proxy=proxy,
        )

        if cache_path:
            _save_auth_cache(session, cache_path)

        return session
    except Exception:
        if tmpdir and os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if pw is not None:
            try:
                pw.stop()
            except Exception:
                pass
        # Restore NODE_EXTRA_CA_CERTS to its previous value so subsequent
        # auth calls (or test runs) are not silently affected.
        if ca_bundle is not None:
            if _prev_node_ca is None:
                os.environ.pop("NODE_EXTRA_CA_CERTS", None)
            else:
                os.environ["NODE_EXTRA_CA_CERTS"] = _prev_node_ca


def _navigate_to_idp(page: Page, product_url: str) -> None:
    """Click through to the IdP login page if needed.

    Workbench shows a "Sign in with OpenID" button that needs clicking.
    Connect often auto-redirects.  This function handles both cases.
    """
    product_base = product_url.rstrip("/").lower()

    # If we're already on an external page (IdP), we're done.
    if not page.url.lower().startswith(product_base):
        return

    # Try clicking sign-in buttons (Workbench pattern).
    for selector in (
        "a:has-text('Sign in with OpenID')",
        "a:has-text('Sign in')",
        "button:has-text('Sign in')",
        "#auth-sign-in-link",
    ):
        try:
            page.click(selector, timeout=int(scaled(3_000)))
            page.wait_for_load_state("domcontentloaded")
            # Check if we left the product page.
            if not page.url.lower().startswith(product_base):
                return
        except Exception:
            continue

    # If we're still on the product page, wait briefly for auto-redirect.
    try:
        page.wait_for_url(
            lambda url: not url.lower().startswith(product_base),
            timeout=int(scaled(10_000)),
        )
    except Exception:
        pass


def _fill_product_login(page: Page, username: str, password: str) -> None:
    """Fill a product's native login form (password/LDAP auth).

    Works for Connect and Workbench login forms that present username
    and password fields directly (not OIDC/SAML redirect flows).
    """
    from vip.idp import _log_verbose

    # Common selectors for Connect and Workbench login forms.
    username_selectors = "#username, input[name='username'], input[type='text']"
    password_selectors = "#password, input[name='password'], input[type='password']"
    submit_selectors = (
        "#signinbutton, #kc-login, "
        "button[type='submit'], input[type='submit'], "
        "button:has-text('Sign in'), button:has-text('Log in')"
    )

    _log_verbose(">>> Filling product login form ...")
    page.locator(username_selectors).first.wait_for(timeout=int(scaled(15_000)))
    page.locator(username_selectors).first.fill(username)
    page.locator(password_selectors).first.fill(password)
    page.locator(submit_selectors).first.click()
    _log_verbose(">>> Product login form submitted.")


def _wait_for_product_redirect(page: Page, product_url: str) -> None:
    """Wait until the browser has returned to the product after IdP auth."""
    base = product_url.rstrip("/").lower()
    deadline = time.monotonic() + scaled(300)  # 5-minute timeout
    clicked_oidc_confirm = False

    while time.monotonic() < deadline:
        try:
            url = page.url.lower()
        except Exception:
            break
        if url.startswith(base) and not _on_login_page(url):
            return
        # Workbench lands on an OIDC confirmation page after the IdP
        # round-trip (form action "auth-openid-sign-in"). A human user
        # would click "Sign in with OpenID"; in headless mode we do it
        # for them. Click at most once so a stuck page doesn't loop.
        if not clicked_oidc_confirm and url.startswith(base):
            if _click_workbench_oidc_confirm(page):
                clicked_oidc_confirm = True
        try:
            page.wait_for_timeout(500)
        except Exception:
            break

    raise RuntimeError(
        "OIDC login did not complete within 5 minutes. "
        "Check credentials, IdP configuration, and MFA setup."
    )


def _click_workbench_oidc_confirm(page: Page) -> bool:
    """Click Workbench's post-OIDC 'Sign in with OpenID' button if present.

    After the IdP round-trip, Workbench shows a confirmation form
    (``<form action="auth-openid-sign-in">``) with a "Sign in with
    OpenID" submit button.  The button POSTs back to Workbench to
    establish the session.  In a headed flow the human clicks it; for
    ``--headless-auth`` we click it automatically.

    Returns ``True`` when a click was issued, ``False`` otherwise (no
    such page, button not visible, or Playwright error).
    """
    from vip.idp import _log_verbose

    selector = "form[action='auth-openid-sign-in'] #signinbutton"
    try:
        btn = page.locator(selector)
        if btn.count() == 0 or not btn.first.is_visible():
            return False
        _log_verbose(">>> Workbench: clicking 'Sign in with OpenID' to complete OIDC flow ...")
        btn.first.click()
        return True
    except PlaywrightError:
        return False


_LOGIN_KEYWORDS = ("sign-in", "login", "auth-sign-in")


def _on_login_page(url: str) -> bool:
    """Return True if *url* looks like a login or IdP page."""
    lower = url.lower()
    return any(kw in lower for kw in _LOGIN_KEYWORDS)


def _authenticate_workbench(page: Page, workbench_url: str) -> str | None:
    """Navigate to Workbench to establish an SSO session.

    After the user authenticated to Connect via OIDC, the identity provider
    already has an active session.  The typical redirect chain is:

    1. Workbench ``/`` → 302 to ``/auth-sign-in``
    2. ``/auth-sign-in`` → (auto-redirect or click) → IdP
    3. IdP (active session) → redirect back to Workbench with token
    4. Workbench sets session cookie → dashboard

    ``networkidle`` may fire at step 2 before the IdP redirect completes,
    so we poll until the URL is on the Workbench domain *and* is no longer
    a login page.

    If SSO does not resolve automatically (e.g. the auth-sign-in page
    requires a click), we attempt to click through.  The headed browser is
    still visible so the user can also intervene manually.

    Returns ``None`` on success, or a short string describing why
    Workbench authentication did not complete.  Callers stash this on
    :class:`InteractiveAuthSession` so test-time skip messages can quote
    the underlying cause instead of guessing.
    """
    wb_base = workbench_url.rstrip("/").lower()
    print(f"\n>>> Authenticating to Workbench at {workbench_url} ...")

    try:
        page.goto(workbench_url)
        page.wait_for_load_state("networkidle")
    except PlaywrightError as exc:
        reason = f"could not reach Workbench at {workbench_url}: {exc}"
        print(
            f">>> Warning: Could not reach Workbench at {workbench_url}: {exc}\n"
            ">>> Verify the URL is correct and accessible. "
            "Workbench tests may be skipped.\n"
        )
        return reason

    # Quick check — already on the Workbench dashboard?
    url = page.url
    if url.lower().startswith(wb_base) and not _on_login_page(url):
        print(">>> Workbench authenticated via SSO.\n")
        return None

    # We're likely on /auth-sign-in.  Try clicking a sign-in button to
    # trigger the OIDC redirect (some Workbench configs don't auto-redirect).
    for selector in (
        "a:has-text('Sign in')",
        "button:has-text('Sign in')",
        "a:has-text('Log in')",
        "button:has-text('Log in')",
        "#auth-sign-in-link",
    ):
        try:
            page.click(selector, timeout=int(scaled(2_000)))
            break
        except Exception:
            continue

    # Wait for the OIDC redirect chain to complete.
    print(">>> Waiting for Workbench SSO redirect chain ...")
    print(">>> If prompted, please complete authentication in the browser.\n")

    deadline = time.monotonic() + scaled(120)  # 2-minute timeout
    last_url = url
    while time.monotonic() < deadline:
        try:
            page.wait_for_load_state("networkidle", timeout=int(scaled(5_000)))
        except Exception:
            pass
        try:
            last_url = page.url
        except Exception:
            break
        if last_url.lower().startswith(wb_base) and not _on_login_page(last_url):
            print(">>> Workbench authenticated.\n")
            return None
        try:
            page.wait_for_timeout(500)
        except Exception:
            break

    print(
        ">>> Warning: Workbench authentication did not complete within 2 minutes.\n"
        ">>> Workbench browser tests may skip.\n"
    )
    return (
        "Workbench authentication did not complete within 2 minutes "
        f"(last URL: {_strip_url_query(last_url)}). "
        "OIDC session may not be shared between Connect and Workbench, "
        "or the auth-sign-in page required interaction."
    )


def _strip_url_query(url: str) -> str:
    """Drop query string and fragment from *url* for safe logging.

    The timeout reason from :func:`_authenticate_workbench` is surfaced
    in the workbench skip message and therefore lands in CI logs and
    test reports.  If the redirect chain stalled mid-OIDC/SAML, the URL
    may carry sensitive parameters like ``code=``, ``state=``, or
    ``SAMLRequest=`` — we keep scheme/host/path for debugging but drop
    the rest.  Returns the input unchanged when it can't be parsed."""
    if not url:
        return url
    try:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except Exception:
        return url


def _httpx_verify(insecure: bool, ca_bundle: Path | None) -> bool | str:
    """Derive the httpx ``verify`` value from TLS config parameters.

    - ``insecure=True`` → ``False`` (skip verification; insecure wins over ca_bundle)
    - ``ca_bundle`` set → ``str`` path to the bundle file
    - default → ``True`` (system trust store)

    Mirrors ``cli.py:391`` and ``VIPConfig.verify`` so TLS behaviour is
    consistent across every httpx call site in auth.py.
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


def _delete_api_key(
    connect_url: str,
    api_key: str,
    key_name: str,
    *,
    insecure: bool = False,
    ca_bundle: Path | None = None,
    proxy: ProxyConfig | None = None,
) -> None:
    """Delete the VIP API key using the key itself for authentication."""

    verify = _httpx_verify_env_aware(insecure, ca_bundle)

    base = connect_url.rstrip("/")
    delete_proxy = proxy_for_url(base, build_proxy_map(proxy))
    with httpx.Client(
        base_url=f"{base}/__api__",
        headers={"Authorization": f"Key {api_key}"},
        timeout=scaled(10.0),
        verify=verify,
        proxy=delete_proxy,
        trust_env=False,
    ) as client:
        for keys_path in ("/v1/user/api_keys", "/keys"):
            resp = client.get(keys_path)
            if resp.status_code == 404:
                continue
            if not resp.is_success:
                print(f">>> Warning: {keys_path} returned HTTP {resp.status_code}")
                continue
            for k in resp.json():
                if k.get("name") == key_name:
                    del_resp = client.delete(f"{keys_path}/{k['id']}")
                    if del_resp.is_success:
                        print(">>> API key deleted.\n")
                    else:
                        print(
                            f">>> Warning: DELETE {keys_path}/{k['id']}"
                            f" returned {del_resp.status_code}"
                        )
                    return
            break
        print(">>> Warning: Could not find API key to delete.\n")


_XSRF_COOKIE_NAMES = ("RSC-XSRF", "RSC-XSRF-legacy")


def _xsrf_from_page(page: Page, request_url: str) -> str:
    """Read the XSRF cookie value from the browser context for ``request_url``.

    Connect's XSRF check compares the cookie value to the ``X-Rsc-Xsrf``
    header.  Production deployments use one of two cookie names:

    * ``RSC-XSRF`` — default on fresh installs.
    * ``RSC-XSRF-legacy`` — set when the server runs in legacy cookie
      mode (e.g. ``connect.posit.it``).  The paired session cookie is
      ``rsconnect-legacy``.  The header name stays ``X-Rsc-Xsrf``.

    Playwright's ``cookies(url)`` filter implements RFC 6265 path
    matching: ``Path=/__api__/`` only matches request paths *under*
    ``/__api__/``.  Pass the actual endpoint URL (e.g.
    ``.../__api__/v1/user``) — not the bare ``/__api__`` base — or
    cookies set with a trailing-slash path get silently excluded and
    Connect replies ``HTTP 403 XSRF token mismatch``.  Reading via the
    cookie jar rather than ``document.cookie`` also handles
    ``HttpOnly`` uniformly.
    """
    try:
        jar = page.context.cookies(request_url) or []
    except PlaywrightError:
        return ""
    by_name = {c.get("name"): c.get("value") or "" for c in jar}
    for name in _XSRF_COOKIE_NAMES:
        if by_name.get(name):
            return by_name[name]
    return ""


def _summarize_cookies(jar: Sequence[Mapping[str, Any]]) -> list[dict]:
    return [
        {
            "name": c.get("name"),
            "domain": c.get("domain"),
            "path": c.get("path"),
            "httpOnly": c.get("httpOnly"),
            "len": len(c.get("value") or ""),
        }
        for c in jar
    ]


def _log_mint_cookie_diagnostic(page: Page, request_url: str) -> None:
    """Print what we see in the browser when minting fails.

    Turns an opaque XSRF mismatch into actionable evidence: the page
    URL, the full jar (to spot cross-domain shadows), the jar filtered
    to the actual endpoint URL under ``/__api__/`` (what truly rides
    the request, respecting RFC 6265 path matching), and
    ``document.cookie`` names.  If these two cookie lists disagree on
    ``RSC-XSRF`` / ``RSC-XSRF-legacy``, the mismatch is almost certainly
    another domain — or a path-scoped cookie — poisoning the unfiltered
    view.
    """
    try:
        current_url = page.url
    except Exception:
        current_url = "<unknown>"
    print(f">>> Mint diagnostic: browser is on {current_url}")
    try:
        jar = page.context.cookies() or []
        print(f">>> Mint diagnostic: full cookie jar ({len(jar)} entries):")
        for entry in _summarize_cookies(jar):
            print(f"    {entry}")
    except Exception as exc:
        print(f">>> Mint diagnostic: could not read cookie jar: {exc}")
    try:
        scoped = page.context.cookies(request_url) or []
        print(f">>> Mint diagnostic: cookies sent to {request_url} ({len(scoped)} entries):")
        for entry in _summarize_cookies(scoped):
            print(f"    {entry}")
    except Exception as exc:
        print(f">>> Mint diagnostic: could not read scoped cookies: {exc}")
    try:
        doc_cookie = page.evaluate("() => document.cookie") or ""
        doc_names = [p.strip().partition("=")[0] for p in doc_cookie.split(";") if p.strip()]
        print(f">>> Mint diagnostic: document.cookie names: {doc_names}")
    except Exception as exc:
        print(f">>> Mint diagnostic: could not read document.cookie: {exc}")


def _response_text(resp) -> str:
    """Read a response body, tolerating both Playwright and httpx shapes.

    Playwright's ``APIResponse.text`` is a method; httpx's is a property.
    Tests sometimes stub it as a plain string.  Duck-type all three.
    """
    text_attr = getattr(resp, "text", None)
    if callable(text_attr):
        return text_attr() or ""
    return text_attr or ""


def _delete_stale_vip_keys(client, guid: str) -> None:
    """Delete ``_vip_interactive_<ts>`` keys older than
    :data:`_ORPHAN_MIN_AGE_SECONDS`.

    Best-effort: network failures and unparseable names are swallowed so a
    single stuck orphan does not block fresh key creation.  Keys younger than
    the threshold are left alone because they probably belong to another
    ``vip verify`` still running.

    *client* is an ``httpx.Client`` already configured with the correct
    ``base_url``, ``verify``, ``cookies``, and ``headers``.  The caller
    constructs it and owns its lifecycle.
    """
    try:
        list_resp = client.get(f"/v1/users/{guid}/keys")
    except Exception as exc:
        print(f">>> Warning: listing stale keys failed: {exc}")
        return
    if not list_resp.is_success:
        return

    now = int(time.time())
    try:
        entries = list_resp.json()
    except ValueError:
        return
    if not isinstance(entries, list):
        print(f">>> Warning: key list response was {type(entries).__name__}, not list.")
        return

    for k in entries:
        if not isinstance(k, dict):
            continue
        name = k.get("name") or ""
        key_id = k.get("id")
        if not name.startswith(_KEY_NAME_PREFIX) or not key_id:
            continue
        suffix = name[len(_KEY_NAME_PREFIX) :]
        try:
            created_ts = int(suffix)
        except ValueError:
            # Legacy key without a timestamp suffix — treat as old.
            created_ts = 0
        if now - created_ts < _ORPHAN_MIN_AGE_SECONDS:
            continue  # belongs to a concurrent run
        try:
            client.delete(f"/v1/users/{guid}/keys/{key_id}")
        except Exception as exc:
            print(f">>> Warning: could not delete stale key {key_id}: {exc}")


def _content_type(resp) -> str:
    """Return the response Content-Type header (or ``"<none>"``) tolerantly.

    Test stubs sometimes use a plain ``MagicMock`` for ``headers``; fall back
    to ``"<none>"`` so the diagnostic line stays readable rather than printing
    a mock repr.
    """
    try:
        headers = getattr(resp, "headers", None) or {}
        value = headers.get("content-type", "<none>")
    except (AttributeError, TypeError):
        return "<none>"
    return value if isinstance(value, str) else "<none>"


def _probe_server_settings(client, base: str, me_status: int, connect_url: str) -> None:
    """Probe ``/__api__/server_settings`` after a mint failure on ``/v1/user``.

    ``/server_settings`` is unauthenticated and lives on the same Connect
    API mount as ``/v1/user``, so if it 404s too, we are simply not hitting
    Connect — the configured ``connect_url`` has the wrong path prefix.
    This turns a confusing "API key minting failed" into a concrete pointer
    at the misconfigured URL (e.g. ``--connect-url .../connect`` when the
    server really lives at the host root).

    Best-effort: any transport error is logged and swallowed.
    """

    try:
        probe = client.get("/server_settings")
    except httpx.HTTPError as exc:
        print(f">>> Mint diagnostic: /server_settings probe failed: {exc}")
        return
    probe_ct = _content_type(probe)
    probe_url = f"{base}/server_settings"
    print(
        f">>> Mint diagnostic: GET {probe_url} returned HTTP "
        f"{probe.status_code} (content-type: {probe_ct})"
    )
    if me_status == 404 and probe.status_code == 404:
        print(
            f">>> Mint diagnostic: both /__api__ endpoints returned 404 — "
            f"the configured connect_url ({connect_url}) likely has the "
            f"wrong path prefix. Try removing any sub-path (e.g. '/connect') "
            f"from --connect-url, or ask the administrator where Connect's "
            f"/__api__/ is mounted."
        )


def _body_snippet(resp, limit: int = 200) -> str:
    """Return a short, single-line preview of an HTTP response body.

    Connect's API error responses include ``error``/``code`` fields that name
    the actual failure reason (CSRF rejection, MFA step-up, etc.).  Including
    a trimmed body snippet in failure warnings turns opaque ``HTTP 403`` into
    something the user can act on.
    """
    try:
        text = _response_text(resp).strip()
    except Exception:
        return "<unreadable body>"
    text = " ".join(text.split())
    return text[:limit] if text else "<empty body>"


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


def _resolve_connect_api_base(
    connect_url: str,
    *,
    insecure: bool = False,
    ca_bundle: Path | None = None,
    proxy: ProxyConfig | None = None,
) -> str:
    """Return a Connect URL whose ``/__api__/`` mount actually responds.

    Some deployments serve the dashboard under a sub-path (``/connect/``)
    but keep the API at the host root.  ``<connect_url>/__api__/`` then
    404s while ``<host>/__api__/`` returns 200.  When that mismatch is
    detected, switch to the host root for API traffic; otherwise return
    the original URL unchanged.

    ``/__api__/server_settings`` is unauthenticated, so probing does not
    need browser cookies.  On any error or ambiguous result, returns the
    original URL so the existing mint diagnostics still run.

    Both probes route through the same proxy the API clients will use, pinned
    with ``trust_env=False`` so the resolved per-URL proxy (which honours
    NO_PROXY) is authoritative rather than httpx re-reading the environment.
    """
    from urllib.parse import urlparse, urlunparse

    if not connect_url:
        return connect_url

    parsed = urlparse(connect_url)
    sub_path = (parsed.path or "").strip("/")
    if not sub_path:
        # Already at host root — nothing to fall back to.
        return connect_url

    verify = _httpx_verify_env_aware(insecure, ca_bundle)
    proxy_map = build_proxy_map(proxy)
    primary = connect_url.rstrip("/") + "/__api__/server_settings"
    try:
        primary_resp = httpx.get(
            primary,
            timeout=scaled(10.0),
            verify=verify,
            follow_redirects=True,
            proxy=proxy_for_url(primary, proxy_map),
            trust_env=False,
        )
    except httpx.HTTPError:
        return connect_url
    if primary_resp.status_code == 200:
        return connect_url

    root = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
    secondary = root + "/__api__/server_settings"
    try:
        secondary_resp = httpx.get(
            secondary,
            timeout=scaled(10.0),
            verify=verify,
            follow_redirects=True,
            proxy=proxy_for_url(secondary, proxy_map),
            trust_env=False,
        )
    except httpx.HTTPError:
        return connect_url
    if secondary_resp.status_code != 200:
        return connect_url

    ct = secondary_resp.headers.get("content-type", "") or ""
    if "json" not in ct.lower():
        return connect_url
    try:
        body = secondary_resp.json()
    except (ValueError, KeyError):
        return connect_url
    if not isinstance(body, dict):
        # JSON 200 that isn't an object (list, scalar, null) cannot be
        # Connect's server_settings payload — treat as ambiguous and
        # keep the original URL.  Without this guard ``body.get(...)``
        # raises ``AttributeError`` and crashes auth.
        return connect_url

    # Require a *positive* match between the root API's advertised
    # ``dashboard_path`` and the sub-path on the configured URL before
    # switching.  A missing or empty ``dashboard_path`` is treated as
    # unverified — keep the original URL rather than blindly routing
    # mint traffic at a JSON endpoint that merely happens to answer 200.
    dashboard_path = (body.get("dashboard_path") or "").strip("/")
    if dashboard_path != sub_path:
        return connect_url

    print(
        f">>> Connect dashboard at {connect_url} but API at {root}/__api__/; "
        f"using {root} for API calls."
    )
    return root


def _create_api_key_via_session(
    page: Page,
    connect_url: str,
    key_name: str,
    *,
    insecure: bool = False,
    ca_bundle: Path | None = None,
    proxy: ProxyConfig | None = None,
) -> str | None:
    """Create a Connect API key by reusing the browser's authenticated session.

    Extracts session cookies from ``page.context.cookies()`` and uses an
    ``httpx.Client`` for all API requests so that ``insecure`` / ``ca_bundle``
    TLS settings are honoured.  Playwright's ``APIRequestContext``
    (``page.context.request``) does not expose a ``verify`` equivalent and
    cannot accept a custom CA bundle, which caused ``CERTIFICATE_VERIFY_FAILED``
    errors when ``--insecure`` was set (issue #239).

    The client is constructed with ``follow_redirects=True`` to match
    ``_resolve_connect_api_base``'s probes: a deployment that redirects
    HTTP -> HTTPS (or drops/adds a trailing slash) would otherwise turn a
    301/302 into a treated-as-failure response here (issue #537).

    The XSRF token is still read from the browser's cookie jar via
    :func:`_xsrf_from_page` and sent as the ``X-Rsc-Xsrf`` request header —
    Connect's double-submit CSRF check requires the header and the cookie to
    match.  The cookie is named ``RSC-XSRF`` on fresh installs and
    ``RSC-XSRF-legacy`` on servers running in legacy cookie mode.

    Hits ``/__api__/v1/users/{guid}/keys`` — the same endpoint the Connect
    dashboard's "+ New API Key" button uses.  See
    https://docs.posit.co/connect/api/ (operationId: createKey).

    Before creating the new key, deletes any lingering ``_vip_interactive_*``
    keys left over from previous runs that crashed before cleanup.  Keys
    younger than :data:`_ORPHAN_MIN_AGE_SECONDS` are skipped so we do not
    delete a concurrent run's live key.

    Returns the API key string, or ``None`` on failure (no exception).

    Note: full end-to-end verification (actual TLS rejection → acceptance with
    ``--insecure``) requires a real self-signed Connect deployment and is not
    covered by selftests.  The ``_httpx_verify`` unit tests confirm the verify
    plumbing; manual testing against a staging cluster is needed to close #239.
    """

    verify = _httpx_verify_env_aware(insecure, ca_bundle)
    base = connect_url.rstrip("/") + "/__api__"
    me_url = f"{base}/v1/user"
    # Mint through the same proxy the product clients will use, resolved for this
    # host (honours NO_PROXY). trust_env=False makes that decision authoritative.
    mint_proxy = proxy_for_url(base, build_proxy_map(proxy))
    # Scope cookie lookup to an actual endpoint path.  RFC 6265 cookie
    # path matching means ``Path=/__api__/`` does *not* match a request
    # to ``/__api__`` (no trailing slash).  Using ``me_url`` matches
    # whatever path the server set the cookie under.
    xsrf = _xsrf_from_page(page, me_url)
    headers = {"X-Rsc-Xsrf": xsrf} if xsrf else {}

    # Build a cookie dict from the browser's session for the Connect API base.
    # We extract cookies for ``me_url`` (under ``/__api__/``) so that
    # path-scoped cookies (e.g. ``Path=/__api__/``) are included — Playwright's
    # RFC 6265-compliant filter excludes them when queried against the bare
    # ``/__api__`` base (no trailing slash).
    try:
        raw_cookies = page.context.cookies(me_url) or []
    except PlaywrightError:
        raw_cookies = []
    cookies = {c["name"]: c["value"] for c in raw_cookies if c.get("name")}

    try:
        with httpx.Client(
            base_url=base,
            headers=headers,
            cookies=cookies,
            timeout=scaled(10.0),
            verify=verify,
            follow_redirects=True,
            proxy=mint_proxy,
            trust_env=False,
        ) as client:
            me_resp = client.get("/v1/user")
            if not me_resp.is_success:
                me_ct = _content_type(me_resp)
                print(
                    f">>> Warning: GET {me_url} returned HTTP "
                    f"{me_resp.status_code} (content-type: {me_ct}): "
                    f"{_body_snippet(me_resp)}"
                )
                xsrf_preview = f"{xsrf[:4]}…(len={len(xsrf)})" if xsrf else "<none>"
                print(f">>> Mint diagnostic: X-Rsc-Xsrf header was {xsrf_preview}")
                _log_mint_cookie_diagnostic(page, me_url)
                _probe_server_settings(client, base, me_resp.status_code, connect_url)
                return None
            guid = me_resp.json().get("guid")
            if not guid:
                print(">>> Warning: Connect did not return a user guid.")
                return None

            _delete_stale_vip_keys(client, guid)

            create_resp = client.post(
                f"/v1/users/{guid}/keys",
                json={"name": key_name},
            )
            if not create_resp.is_success:
                print(
                    f">>> Warning: POST /v1/users/{guid}/keys returned HTTP "
                    f"{create_resp.status_code}: {_body_snippet(create_resp)}"
                )
                return None

            created = create_resp.json()
            if not isinstance(created, dict):
                # A 301/302 on the POST is followed as a GET -- httpx
                # downgrades the method exactly as browsers and curl do, and
                # only 307/308 preserve it.  The downgraded GET lands on the
                # same path, which is the key-*listing* route, so a JSON array
                # comes back instead of the created key.  Without this guard
                # ``.get("key")`` raises ``AttributeError``, which is not in
                # the caught tuple below and so crashes auth outright (#561).
                print(
                    ">>> Warning: POST /v1/users/<guid>/keys returned a "
                    f"{type(created).__name__}, not an object. A proxy most "
                    "likely redirected the request with 301/302, which turns "
                    "the POST into a GET of the key-listing route. Configure "
                    "the proxy to redirect with 307/308, or point --connect-url "
                    "at the final URL so no redirect is needed."
                )
                return None

            api_key = created.get("key")
            if not api_key:
                print(">>> Warning: Connect response did not include a key string.")
                return None

            print(">>> Connect API key created.\n")
            return api_key
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        # httpx.HTTPError catches both transport-level failures (DNS, TCP,
        # TLS, timeouts -- httpx.RequestError) and HTTP status errors
        # (httpx.HTTPStatusError).  Mirrors the prior PlaywrightError
        # handling: the function is documented to return None on failure
        # rather than raising, so vip verify can emit a warning instead of
        # crashing during auth setup.
        print(f">>> Warning: Could not create API key: {exc}")
        return None
