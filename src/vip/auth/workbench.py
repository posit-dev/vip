"""Workbench post-SSO login handling."""

from __future__ import annotations

import time

from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    Page,
)

from vip.auth.sso import (
    _IDP_ROUNDTRIP_TIMEOUT_SECONDS,
    _protocol_label,
    _strip_url_query,
    _timeout_label,
)
from vip.timeouts import scaled


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


_LOGIN_KEYWORDS = ("sign-in", "login", "auth-sign-in", "/saml/acs")


def _on_login_page(url: str) -> bool:
    """Return True if *url* looks like a login page or an in-flight auth callback.

    ``/saml/acs`` is Workbench's SAML Assertion Consumer Service endpoint --
    the raw POST target the IdP redirects to before Workbench validates the
    assertion and issues its own session cookie. Every caller here uses this
    check to decide "is the round-trip actually finished", and landing on
    that URL means it is not: :func:`_authenticate_workbench` and
    :func:`_wait_for_product_redirect` must not treat ``networkidle`` firing
    as completion while still on this URL, because Workbench's own
    post-assertion redirect has not run yet -- accepting it early captures a
    storage state with no valid Workbench session cookie, so a real SAML
    login looks successful during --headless-auth but fails once
    ``test_workbench_login`` reuses that state.
    """
    lower = url.lower()
    return any(kw in lower for kw in _LOGIN_KEYWORDS)


def _authenticate_workbench(page: Page, workbench_url: str, *, provider: str = "") -> str | None:
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

    *provider* names the configured auth provider (``"oidc"``, ``"saml"``,
    ``"oauth2"``), same convention as :func:`_wait_for_product_redirect`, so
    the timeout reason names the protocol that actually ran instead of
    assuming OIDC (see #263). Leave it as "" when unknown here; the message
    falls back to neutral wording.

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
        print(f">>> Workbench authenticated via SSO. Landed at: {url}\n")
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
        except PlaywrightError:
            continue

    # Wait for the OIDC redirect chain to complete.
    print(">>> Waiting for Workbench SSO redirect chain ...")
    print(">>> If prompted, please complete authentication in the browser.\n")

    # Share the single round-trip timeout (see _IDP_ROUNDTRIP_TIMEOUT_SECONDS)
    # rather than this function's own, shorter one.
    deadline = time.monotonic() + scaled(_IDP_ROUNDTRIP_TIMEOUT_SECONDS)
    last_url = url
    while time.monotonic() < deadline:
        try:
            page.wait_for_load_state("networkidle", timeout=int(scaled(5_000)))
        except PlaywrightError:
            pass
        try:
            last_url = page.url
        except PlaywrightError:
            break
        if last_url.lower().startswith(wb_base) and not _on_login_page(last_url):
            print(f">>> Workbench authenticated. Landed at: {last_url}\n")
            return None
        try:
            page.wait_for_timeout(500)
        except PlaywrightError:
            break

    timeout_label = _timeout_label(scaled(_IDP_ROUNDTRIP_TIMEOUT_SECONDS))
    try:
        last_title = page.title()
    except PlaywrightError:
        last_title = "<unknown>"
    label = _protocol_label(provider)
    session_desc = f"{label} session" if label else "The login session"
    print(
        f">>> Warning: Workbench authentication did not complete within {timeout_label}.\n"
        ">>> Workbench browser tests may skip.\n"
    )
    return (
        f"Workbench authentication did not complete within {timeout_label} "
        f"(last URL: {_strip_url_query(last_url)}, page title: {last_title!r}). "
        f"{session_desc} may not be shared between Connect and Workbench, "
        "or the auth-sign-in page required interaction."
    )
