"""Chromium launch, :class:`InteractiveAuthSession`, and :func:`authenticated_page`."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    Page,
    sync_playwright,
)

from vip.auth.apikey import _delete_api_key
from vip.errors import AuthConfigError
from vip.proxy import (
    ProxyConfig,
    build_proxy_map,
    chromium_launch_args,
    playwright_proxy,
)

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
            except (httpx.HTTPError, httpx.InvalidURL, ValueError, KeyError, AttributeError) as exc:
                print(f">>> Warning: Could not delete API key: {exc}")

        if self._tmpdir and Path(self._tmpdir).is_dir():
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
            except (PlaywrightError, OSError, RuntimeError):
                pass
    finally:
        if browser is not None:
            try:
                browser.close()
            except (PlaywrightError, OSError, RuntimeError):
                pass
        if pw is not None:
            try:
                pw.stop()
            except (PlaywrightError, OSError, RuntimeError):
                pass
        if ca_bundle is not None:
            if _prev_node_ca is None:
                os.environ.pop("NODE_EXTRA_CA_CERTS", None)
            else:
                os.environ["NODE_EXTRA_CA_CERTS"] = _prev_node_ca
