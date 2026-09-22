"""IdP navigation, product login form, redirect wait, and timeout-message helpers."""

from __future__ import annotations

import time

from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    Page,
)

from vip.errors import AuthTimeoutError
from vip.timeouts import scaled

# Single timeout for an IdP login round-trip (browser leaves the product,
# authenticates at the IdP, and lands back). Shared by the interactive poll
# loop, the headless _wait_for_product_redirect poll, and
# _authenticate_workbench's post-Connect SSO wait, so Workbench's wait can
# never expire before the primary round-trip's window does.
_IDP_ROUNDTRIP_TIMEOUT_SECONDS = 300


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
        except PlaywrightError:
            continue

    # If we're still on the product page, wait briefly for auto-redirect.
    try:
        page.wait_for_url(
            lambda url: not url.lower().startswith(product_base),
            timeout=int(scaled(10_000)),
        )
    except PlaywrightError:
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


def _wait_for_product_redirect(page: Page, product_url: str, *, provider: str = "") -> None:
    """Wait until the browser has returned to the product after IdP auth.

    *provider* names the configured auth provider (``"oidc"``, ``"saml"``,
    ``"oauth2"``) so a timeout error names the protocol that actually ran
    instead of assuming OIDC (see #263). Leave it as "" when unknown here;
    the message falls back to neutral wording.
    """
    # Imported here because vip.auth.workbench imports this module's helpers.
    from vip.auth.workbench import _click_workbench_oidc_confirm, _on_login_page

    base = product_url.rstrip("/").lower()
    deadline = time.monotonic() + scaled(_IDP_ROUNDTRIP_TIMEOUT_SECONDS)
    clicked_oidc_confirm = False

    while time.monotonic() < deadline:
        try:
            url = page.url.lower()
        except PlaywrightError:
            break
        if url.startswith(base) and not _on_login_page(url):
            return
        # Workbench lands on an OIDC confirmation page after the IdP
        # round-trip (form action "auth-openid-sign-in"). A human user
        # would click "Sign in with OpenID"; in headless mode we do it
        # for them. Click at most once so a stuck page doesn't loop.
        if (
            not clicked_oidc_confirm
            and url.startswith(base)
            and _click_workbench_oidc_confirm(page)
        ):
            clicked_oidc_confirm = True
        try:
            page.wait_for_timeout(500)
        except PlaywrightError:
            break

    label = _protocol_label(provider)
    verb = f"{label} login" if label else "Login"
    state = _describe_final_page_state(page, product_url)
    raise AuthTimeoutError(
        f"{verb} did not complete within "
        f"{_timeout_label(scaled(_IDP_ROUNDTRIP_TIMEOUT_SECONDS))}. "
        f"Check credentials, IdP configuration, and MFA setup. Browser {state}."
    )


def _strip_url_query(url: str) -> str:
    """Drop query string and fragment from *url* for safe logging.

    The timeout reason from :func:`_authenticate_workbench` is surfaced
    in the workbench skip message and therefore lands in CI logs and
    test reports.  If the redirect chain stalled mid-OIDC/SAML, the URL
    may carry sensitive parameters like ``code=``, ``state=``, or
    ``SAMLRequest=`` — we keep scheme/host/path for debugging but drop
    the rest.  Returns the input unchanged when it can't be parsed.
    """
    if not url:
        return url
    try:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except ValueError:
        return url


def _describe_final_page_state(page: Page, expected_origin: str) -> str:
    """Best-effort description of where the browser ended up, for a
    timeout error.

    Before this, a redirect timeout said only "did not complete" -- never
    where the browser actually was, so a SAML diagnostic run couldn't tell
    whether it never left the IdP, bounced back to the product's own
    sign-in page, or something else entirely (see #263). Every read here is
    guarded: the page may already be closed or crashed by the time the
    deadline fires, and a diagnostic must never itself raise and mask the
    original timeout.
    """
    try:
        url = _strip_url_query(page.url)
    except Exception:  # noqa: BLE001 -- diagnostic-only; see docstring, must never mask the timeout
        url = "<unknown -- page may be closed or crashed>"
    try:
        title = page.title()
    except Exception:  # noqa: BLE001 -- diagnostic-only; see docstring, must never mask the timeout
        title = "<unknown>"
    return f"ended up at {url!r} (title: {title!r}); expected to land on {expected_origin!r}"


_PROVIDER_LABELS = {"oidc": "OIDC", "saml": "SAML", "oauth2": "OAuth2"}


def _protocol_label(provider: str) -> str:
    """Human-readable protocol name for *provider*, or "" when it isn't a
    recognized IdP-backed provider.

    Callers use this to name the protocol actually configured in a timeout
    error message, rather than hardcoding one that could be wrong (e.g.
    "OIDC" during a SAML run); an unrecognized provider falls back to
    neutral wording ("Login", not a wrong protocol name).
    """
    return _PROVIDER_LABELS.get(provider.strip().lower(), "")


def _timeout_label(seconds: float) -> str:
    """Human-readable minutes for a *scaled* timeout.

    Derives the text from the real, already-scaled deadline (e.g.
    ``scaled(300)``) so the reported minutes always match how long VIP
    actually waits, including under ``VIP_TIMEOUT_SCALE``.
    """
    minutes = seconds / 60
    if minutes == int(minutes):
        n = int(minutes)
        return f"{n} minute{'s' if n != 1 else ''}"
    return f"{minutes:.1f} minutes"
