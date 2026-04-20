"""Interactive browser authentication for OIDC providers.

Opens a headed Chromium browser for the user to complete an OIDC login
flow, mints a temporary Connect API key by calling the Connect REST API
with the browser's session cookies, saves the browser storage state, then
closes the browser before tests start.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
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
    "    uv run playwright install --with-deps chromium"
)


def _launch_chromium(pw, *, headless: bool):
    """Launch Chromium via Playwright, turning missing-system-deps errors
    into a clear :class:`AuthConfigError` with a remediation command.

    Other Playwright errors (e.g. an already-running browser) propagate
    unchanged so callers can surface them as needed.
    """
    try:
        return pw.chromium.launch(headless=headless)
    except PlaywrightError as exc:
        text = str(exc).lower()
        if any(signal in text for signal in _MISSING_DEPS_SIGNALS):
            raise AuthConfigError(_MISSING_DEPS_HINT) from exc
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

    _connect_url: str = field(default="", repr=False)
    _tmpdir: str = field(default="", repr=False)

    def cleanup(self) -> None:
        """Delete the minted API key and remove the temp directory."""
        if self.api_key and self._connect_url:
            try:
                _delete_api_key(self._connect_url, self.api_key, self.key_name)
            except Exception as exc:
                print(f">>> Warning: Could not delete API key: {exc}")

        if self._tmpdir and os.path.isdir(self._tmpdir):
            shutil.rmtree(self._tmpdir, ignore_errors=True)


def _load_cached_auth(cache_path: Path) -> InteractiveAuthSession | None:
    """Load a cached auth session if the storage state file exists and is recent."""
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
    connect_url = ""
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            api_key = meta.get("api_key")
            key_name = meta.get("key_name", "")
            connect_url = meta.get("connect_url", "")
        except Exception:
            pass

    print(f">>> Reusing cached auth session from {cache_path}")
    return InteractiveAuthSession(
        storage_state_path=cache_path,
        api_key=api_key,
        key_name=key_name,
        _connect_url=connect_url,
        _tmpdir="",
    )


def _save_auth_cache(session: InteractiveAuthSession, cache_path: Path) -> None:
    """Save auth session metadata alongside the storage state."""
    import json
    import shutil as _shutil

    # Copy storage state to the cache location.
    _shutil.copy2(session.storage_state_path, cache_path)
    os.chmod(cache_path, 0o600)

    # Write companion metadata.
    meta_path = cache_path.with_suffix(".meta.json")
    meta = {
        "api_key": session.api_key,
        "key_name": session.key_name,
        "connect_url": session._connect_url,
    }
    meta_path.write_text(json.dumps(meta))
    os.chmod(meta_path, 0o600)


def start_interactive_auth(
    connect_url: str | None = None,
    workbench_url: str | None = None,
    cache_path: Path | None = None,
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
    """
    if not connect_url and not workbench_url:
        raise ValueError(
            "--interactive-auth requires at least one product URL (Connect or Workbench)"
        )

    # Check for a valid cached session.
    if cache_path:
        cached = _load_cached_auth(cache_path)
        if cached is not None:
            return cached

    # Determine the primary login target.
    primary_url = connect_url or workbench_url
    assert primary_url is not None  # guaranteed by the check above
    login_path = "/__login__" if connect_url else ""

    tmpdir = tempfile.mkdtemp(prefix="vip-auth-")
    storage_state_path = Path(tmpdir) / "vip-auth-state.json"
    os.chmod(tmpdir, 0o700)

    key_name = f"{_KEY_NAME_PREFIX}{int(time.time())}"

    pw = None
    browser = None
    try:
        pw = sync_playwright().start()
        browser = _launch_chromium(pw, headless=False)
        context = browser.new_context()
        page = context.new_page()

        page.goto(f"{primary_url}{login_path}")

        print(f"\n>>> A browser window has opened at {primary_url}")
        print(">>> Please log in through your identity provider.")
        print(">>> The browser will close automatically after login.\n")

        # Poll until login completes
        base = primary_url.rstrip("/")
        deadline = time.monotonic() + 300
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

        # Mint Connect API key only if Connect is configured.
        api_key = None
        if connect_url:
            api_key = _create_api_key_via_session(page, connect_url, key_name)

        # Visit Workbench so the storage state includes its session cookies.
        if workbench_url and connect_url:
            _authenticate_workbench(page, workbench_url)

        context.storage_state(path=str(storage_state_path))

        session = InteractiveAuthSession(
            storage_state_path=storage_state_path,
            api_key=api_key,
            key_name=key_name,
            _connect_url=connect_url or "",
            _tmpdir=tmpdir,
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
) -> InteractiveAuthSession:
    """Launch a headless browser, automate OIDC login, and optionally
    mint a Connect API key through the UI.

    This is the headless counterpart to ``start_interactive_auth()``.
    Instead of showing a browser window for manual login, it fills the
    IdP login form automatically and prompts via the terminal for MFA
    codes when needed.

    At least one of *connect_url* or *workbench_url* must be provided.
    The *idp* parameter selects which form automation strategy to use
    (e.g. ``"keycloak"``, ``"okta"``).
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
        cached = _load_cached_auth(cache_path)
        if cached is not None:
            return cached

    if not username or not password:
        raise AuthConfigError(
            "--headless-auth requires test credentials. "
            "Set VIP_TEST_USERNAME and VIP_TEST_PASSWORD."
        )

    # Choose login flow based on auth provider, not idp presence.
    # OIDC/SAML/OAuth2 → IdP form automation; password/LDAP → native form.
    uses_idp = provider.strip().lower() in _IDP_PROVIDERS
    fill_login = None
    if uses_idp:
        if not idp:
            raise AuthConfigError(
                f"--headless-auth with provider={provider!r} requires"
                ' [auth] idp in vip.toml (supported: "keycloak", "okta")'
            )
        from vip.idp import get_idp_strategy

        fill_login = get_idp_strategy(idp)

    # Determine the primary login target.
    primary_url = connect_url or workbench_url
    assert primary_url is not None
    login_path = "/__login__" if connect_url else ""

    tmpdir = tempfile.mkdtemp(prefix="vip-auth-")
    storage_state_path = Path(tmpdir) / "vip-auth-state.json"
    os.chmod(tmpdir, 0o700)

    key_name = f"{_KEY_NAME_PREFIX}{int(time.time())}"

    pw = None
    browser = None
    try:
        pw = sync_playwright().start()
        browser = _launch_chromium(pw, headless=True)
        context = browser.new_context()
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

        # Mint Connect API key only if Connect is configured.
        api_key = None
        if connect_url:
            api_key = _create_api_key_via_session(page, connect_url, key_name)

        # Visit Workbench so the storage state includes its session cookies.
        if workbench_url and connect_url:
            _authenticate_workbench(page, workbench_url)

        context.storage_state(path=str(storage_state_path))

        session = InteractiveAuthSession(
            storage_state_path=storage_state_path,
            api_key=api_key,
            key_name=key_name,
            _connect_url=connect_url or "",
            _tmpdir=tmpdir,
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
            page.click(selector, timeout=3_000)
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
            timeout=10_000,
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
    page.locator(username_selectors).first.wait_for(timeout=15_000)
    page.locator(username_selectors).first.fill(username)
    page.locator(password_selectors).first.fill(password)
    page.locator(submit_selectors).first.click()
    _log_verbose(">>> Product login form submitted.")


def _wait_for_product_redirect(page: Page, product_url: str) -> None:
    """Wait until the browser has returned to the product after IdP auth."""
    base = product_url.rstrip("/").lower()
    deadline = time.monotonic() + 300  # 5-minute timeout

    while time.monotonic() < deadline:
        try:
            url = page.url.lower()
        except Exception:
            break
        if url.startswith(base) and not _on_login_page(url):
            return
        try:
            page.wait_for_timeout(500)
        except Exception:
            break

    raise RuntimeError(
        "OIDC login did not complete within 5 minutes. "
        "Check credentials, IdP configuration, and MFA setup."
    )


_LOGIN_KEYWORDS = ("sign-in", "login", "auth-sign-in")


def _on_login_page(url: str) -> bool:
    """Return True if *url* looks like a login or IdP page."""
    lower = url.lower()
    return any(kw in lower for kw in _LOGIN_KEYWORDS)


def _authenticate_workbench(page: Page, workbench_url: str) -> None:
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
    """
    wb_base = workbench_url.rstrip("/").lower()
    print(f"\n>>> Authenticating to Workbench at {workbench_url} ...")

    page.goto(workbench_url)
    page.wait_for_load_state("networkidle")

    # Quick check — already on the Workbench dashboard?
    url = page.url
    if url.lower().startswith(wb_base) and not _on_login_page(url):
        print(">>> Workbench authenticated via SSO.\n")
        return

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
            page.click(selector, timeout=2_000)
            break
        except Exception:
            continue

    # Wait for the OIDC redirect chain to complete.
    print(">>> Waiting for Workbench SSO redirect chain ...")
    print(">>> If prompted, please complete authentication in the browser.\n")

    deadline = time.monotonic() + 120  # 2-minute timeout
    while time.monotonic() < deadline:
        try:
            page.wait_for_load_state("networkidle", timeout=5_000)
        except Exception:
            pass
        try:
            url = page.url
        except Exception:
            break
        if url.lower().startswith(wb_base) and not _on_login_page(url):
            print(">>> Workbench authenticated.\n")
            return
        try:
            page.wait_for_timeout(500)
        except Exception:
            break

    print(
        ">>> Warning: Workbench authentication did not complete within 2 minutes.\n"
        ">>> Workbench browser tests may skip.\n"
    )


def _delete_api_key(connect_url: str, api_key: str, key_name: str) -> None:
    """Delete the VIP API key using the key itself for authentication."""
    import httpx

    base = connect_url.rstrip("/")
    with httpx.Client(
        base_url=f"{base}/__api__",
        headers={"Authorization": f"Key {api_key}"},
        timeout=10.0,
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


def _delete_stale_vip_keys(client, guid: str) -> None:
    """Delete ``_vip_interactive_<ts>`` keys older than
    :data:`_ORPHAN_MIN_AGE_SECONDS`.

    Best-effort: network failures and unparseable names are swallowed so a
    single stuck orphan does not block fresh key creation.  Keys younger than
    the threshold are left alone because they probably belong to another
    ``vip verify`` still running.
    """
    import httpx

    try:
        list_resp = client.get(f"/v1/users/{guid}/keys")
    except httpx.HTTPError as exc:
        print(f">>> Warning: listing stale keys failed: {exc}")
        return
    if not list_resp.is_success:
        return

    now = int(time.time())
    try:
        entries = list_resp.json()
    except ValueError:
        return

    for k in entries:
        name = k.get("name") or ""
        if not name.startswith(_KEY_NAME_PREFIX):
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
            client.delete(f"/v1/users/{guid}/keys/{k['id']}")
        except httpx.HTTPError as exc:
            print(f">>> Warning: could not delete stale key {k.get('id')}: {exc}")


def _create_api_key_via_session(page: Page, connect_url: str, key_name: str) -> str | None:
    """Create a Connect API key using the browser's session cookies.

    Lifts cookies from the authenticated Playwright context and POSTs to
    ``/__api__/v1/users/{guid}/keys`` — the same endpoint the Connect
    dashboard's "+ New API Key" button uses.  See
    https://docs.posit.co/connect/api/ (operationId: createKey).

    Before creating the new key, deletes any lingering ``_vip_interactive_*``
    keys left over from previous runs that crashed before cleanup.  Keys
    younger than :data:`_ORPHAN_MIN_AGE_SECONDS` are skipped so we do not
    delete a concurrent run's live key.

    Returns the API key string, or ``None`` on failure (no exception).
    """
    import httpx

    base = connect_url.rstrip("/")
    # Scope cookies to the Connect host so IdP cookies (which can be large
    # and irrelevant) aren't sent to Connect.
    cookies = {c["name"]: c["value"] for c in page.context.cookies(connect_url)}
    xsrf = cookies.get("RSC-XSRF", "")
    headers = {"X-Rsc-Xsrf": xsrf} if xsrf else {}

    try:
        with httpx.Client(
            base_url=f"{base}/__api__",
            cookies=cookies,
            headers=headers,
            timeout=10.0,
        ) as client:
            me_resp = client.get("/v1/user")
            if not me_resp.is_success:
                print(f">>> Warning: GET /v1/user returned HTTP {me_resp.status_code}")
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
                    f"{create_resp.status_code}"
                )
                return None

            api_key = create_resp.json().get("key")
            if not api_key:
                print(">>> Warning: Connect response did not include a key string.")
                return None

            print(">>> Connect API key created.\n")
            return api_key
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        print(f">>> Warning: Could not create API key: {exc}")
        return None
