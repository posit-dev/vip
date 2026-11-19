"""Interactive and headless auth orchestrators across Connect and Workbench."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

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

from vip import totp
from vip.auth.apikey import _KEY_NAME_PREFIX, _create_api_key_via_session, _resolve_connect_api_base
from vip.auth.browser import InteractiveAuthSession, _launch_chromium
from vip.auth.cache import _load_cached_auth, _save_auth_cache
from vip.auth.scheme import resolve_url_scheme
from vip.auth.sso import (
    _IDP_ROUNDTRIP_TIMEOUT_SECONDS,
    _describe_final_page_state,
    _fill_product_login,
    _navigate_to_idp,
    _timeout_label,
)
from vip.auth.workbench import _authenticate_workbench, _wait_for_product_redirect
from vip.config import ProductConfig
from vip.errors import AuthConfigError, AuthTimeoutError
from vip.idp import SUPPORTED_IDPS, _sanitize_url, get_idp_strategy
from vip.output import Verbosity, debug, get_verbosity, info, set_verbosity, warn
from vip.proxy import (
    ProxyConfig,
    build_proxy_map,
    chromium_launch_args,
    playwright_proxy,
)
from vip.timeouts import scaled


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
    # the auth selftests plus plugin/ and cli/ -- out of scope for this bug fix.
    pc = ProductConfig(url=url)
    pc.url_scheme_inferred = inferred
    return resolve_url_scheme(pc, insecure=insecure, ca_bundle=ca_bundle, proxy=proxy)


def _cached_session(
    cache_path: Path | None,
    connect_url: str | None,
    workbench_url: str | None,
    *,
    insecure: bool,
    ca_bundle: Path | None,
    proxy: ProxyConfig | None,
) -> InteractiveAuthSession | None:
    """Return a valid cached session for the given URLs, or ``None``."""
    if not cache_path:
        return None
    return _load_cached_auth(
        cache_path,
        connect_url,
        workbench_url,
        insecure=insecure,
        ca_bundle=ca_bundle,
        proxy=proxy,
    )


# A login step drives *page* through the login and returns once the browser is
# authenticated.  It receives the primary URL, the URL to open first, and whether
# Connect is configured.
LoginStep = Callable[[Page, str, str, bool], None]


def _run_login(
    *,
    connect_url: str | None,
    workbench_url: str | None,
    cache_path: Path | None,
    insecure: bool,
    ca_bundle: Path | None,
    connect_url_scheme_inferred: bool,
    workbench_url_scheme_inferred: bool,
    proxy: ProxyConfig | None,
    headed: bool,
    do_login: LoginStep,
    workbench_provider: str = "",
) -> InteractiveAuthSession:
    """Run the browser login shared by the interactive and headless entry points.

    Callers check the auth cache and validate their inputs first.  This
    resolves the URLs, launches Chromium (*headed* or headless), runs
    *do_login*, mints the Connect API key, visits Workbench, and returns the
    session.  *workbench_provider* only selects the protocol wording in
    Workbench timeout messages.
    """
    # Resolve inferred https:// schemes after every fail-fast validation and
    # right before anything (Playwright or httpx) talks to the URLs, so a config
    # error never pays for a network probe it doesn't need.
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
    if primary_url is None:
        raise RuntimeError("unreachable: connect_url or workbench_url required, checked above")
    login_path = "/__login__" if connect_url else ""

    tmpdir = tempfile.mkdtemp(prefix="vip-auth-")
    storage_state_path = Path(tmpdir) / "vip-auth-state.json"
    Path(tmpdir).chmod(0o700)

    key_name = f"{_KEY_NAME_PREFIX}{int(time.time())}"

    # Route the browser login through the same proxy as VIP's httpx egress, so
    # it does not silently take a different network path than the API-key mint
    # and the product clients (Chromium's implicit env-proxy detection is
    # platform-dependent).  Resolved for ``primary_url`` -- the URL this browser
    # is about to navigate -- so an http:// product selects the http proxy.
    pw_proxy = playwright_proxy(build_proxy_map(proxy), primary_url)
    pw_args = chromium_launch_args(proxy)

    pw = None
    browser = None
    _prev_node_ca = os.environ.get("NODE_EXTRA_CA_CERTS")
    if ca_bundle is not None:
        os.environ["NODE_EXTRA_CA_CERTS"] = str(ca_bundle)
    try:
        pw = sync_playwright().start()
        browser = _launch_chromium(pw, headless=not headed, proxy=pw_proxy, args=pw_args)
        context = browser.new_context(ignore_https_errors=insecure)
        page = context.new_page()

        do_login(page, primary_url, f"{primary_url}{login_path}", bool(connect_url))

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
            workbench_auth_error = _authenticate_workbench(
                page, workbench_url, provider=workbench_provider
            )

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
        if tmpdir and Path(tmpdir).is_dir():
            shutil.rmtree(tmpdir, ignore_errors=True)
        raise
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
        # Restore NODE_EXTRA_CA_CERTS to its previous value so subsequent
        # auth calls (or test runs) are not silently affected.
        if ca_bundle is not None:
            if _prev_node_ca is None:
                os.environ.pop("NODE_EXTRA_CA_CERTS", None)
            else:
                os.environ["NODE_EXTRA_CA_CERTS"] = _prev_node_ca


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

    cached = _cached_session(
        cache_path, connect_url, workbench_url, insecure=insecure, ca_bundle=ca_bundle, proxy=proxy
    )
    if cached is not None:
        return cached

    def login(page: Page, primary_url: str, target: str, has_connect: bool) -> None:
        page.goto(target)

        warn(f"\n>>> A browser window has opened at {primary_url}")
        warn(">>> Please log in through your identity provider.")
        warn(">>> The browser will close automatically after login.\n")

        # Poll until login completes
        base = primary_url.rstrip("/")
        deadline = time.monotonic() + scaled(_IDP_ROUNDTRIP_TIMEOUT_SECONDS)
        login_completed = False

        # Login detection: for Connect check we left /__login__,
        # for Workbench check we're no longer on a login/auth page.
        while time.monotonic() < deadline:
            try:
                url = page.url
            except PlaywrightError:
                break
            if has_connect:
                if base in url and "/__login__" not in url:
                    login_completed = True
                    break
            else:
                # For Workbench, login is complete when we're on the
                # homepage (no login/auth keywords in the URL).
                lower = url.lower()
                at_login = any(kw in lower for kw in ("sign-in", "login", "auth", "/saml/acs"))
                if base.rstrip("/").lower() in lower and not at_login:
                    login_completed = True
                    break
            try:
                page.wait_for_timeout(500)
            except PlaywrightError:
                break

        if not login_completed:
            state = _describe_final_page_state(page, primary_url)
            raise AuthTimeoutError(
                "Login did not complete within "
                f"{_timeout_label(scaled(_IDP_ROUNDTRIP_TIMEOUT_SECONDS))}. "
                "Please rerun and complete authentication in the browser window. "
                f"Browser {state}."
            )

    return _run_login(
        connect_url=connect_url,
        workbench_url=workbench_url,
        cache_path=cache_path,
        insecure=insecure,
        ca_bundle=ca_bundle,
        connect_url_scheme_inferred=connect_url_scheme_inferred,
        workbench_url_scheme_inferred=workbench_url_scheme_inferred,
        proxy=proxy,
        headed=True,
        do_login=login,
    )


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
    (e.g. ``"keycloak"``, ``"okta"``, ``"snowflake"``, ``"entra"``).

    When *insecure* is ``True``, Playwright ignores TLS certificate errors.
    When *ca_bundle* is set, the path is exported as ``NODE_EXTRA_CA_CERTS``
    before launching Chromium so it trusts a custom CA (Chromium-level trust
    only; this does not update the OS certificate store).

    *connect_url_scheme_inferred* / *workbench_url_scheme_inferred*: see
    ``start_interactive_auth``.
    """
    # ``-q`` wins over the legacy ``--vip-verbose`` flag, matching the CLI's precedence.
    if verbose and get_verbosity() is not Verbosity.QUIET:
        set_verbosity(Verbosity.VERBOSE)

    if not connect_url and not workbench_url:
        raise AuthConfigError(
            "--headless-auth requires at least one product URL (Connect or Workbench)"
        )

    cached = _cached_session(
        cache_path, connect_url, workbench_url, insecure=insecure, ca_bundle=ca_bundle, proxy=proxy
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
    totp_secret = os.environ.get(totp.ENV_VAR, "").strip()
    if totp_secret:
        totp.validate_secret(totp_secret)

    # Choose login flow based on auth provider, not idp presence.
    # OIDC/SAML/OAuth2 → IdP form automation; password/LDAP → native form.
    uses_idp = provider.strip().lower() in _IDP_PROVIDERS
    fill_login = None
    if uses_idp:
        if not idp:
            supported = ", ".join(f'"{name}"' for name in sorted(SUPPORTED_IDPS))
            raise AuthConfigError(
                f"--headless-auth with provider={provider!r} requires"
                f" [auth] idp in vip.toml (supported: {supported})"
            )

        fill_login = get_idp_strategy(idp)

    def login(page: Page, primary_url: str, target: str, has_connect: bool) -> None:
        info(f"\n>>> Headless auth: authenticating to {primary_url} ...")
        try:
            page.goto(target)
            page.wait_for_load_state("domcontentloaded")
            debug(f">>> Page loaded, URL: {_sanitize_url(page.url)}")

            if fill_login:
                # OIDC/SAML: navigate to IdP and automate its login form.
                _navigate_to_idp(page, primary_url)
                debug(f">>> At IdP login page: {_sanitize_url(page.url)}")
                fill_login(page, username, password)
            else:
                # Password/LDAP: fill the product's native login form directly.
                _fill_product_login(page, username, password)

            # Wait for redirect back to the product.
            _wait_for_product_redirect(
                page, primary_url, provider=provider, check_connect_session=has_connect
            )
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
        info(">>> Authentication complete.")

    return _run_login(
        connect_url=connect_url,
        workbench_url=workbench_url,
        cache_path=cache_path,
        insecure=insecure,
        ca_bundle=ca_bundle,
        connect_url_scheme_inferred=connect_url_scheme_inferred,
        workbench_url_scheme_inferred=workbench_url_scheme_inferred,
        proxy=proxy,
        headed=False,
        do_login=login,
        workbench_provider=provider,
    )
