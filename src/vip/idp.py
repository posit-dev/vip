"""IdP login form strategies for headless OIDC authentication.

Each strategy automates a specific identity provider's login form using
Playwright.  Strategies fill username/password and handle MFA prompting
via the terminal when the IdP presents a second-factor challenge.
"""

from __future__ import annotations

from collections.abc import Callable

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

# Keycloak selectors — validated by PPM's e2e test suite.
_KC_USERNAME = "input[id='username']"
_KC_PASSWORD = "input[id='password']"
_KC_SUBMIT = "button[id='kc-login']"
_KC_OTP = "input[id='otp']"

# Okta selectors.
_OKTA_IDENTIFIER = "input[name='identifier']"
_OKTA_PASSCODE = "input[name='credentials.passcode']"
_OKTA_SUBMIT = "input[type='submit'], button[type='submit']"

# Timeout for waiting on form elements (ms).
_FORM_TIMEOUT = 15_000
# Timeout for detecting whether MFA is required after login submit (ms).
_MFA_DETECT_TIMEOUT = 10_000
# Timeout for MFA completion after user is prompted (ms).
_MFA_TIMEOUT = 300_000  # 5 minutes


def _print_flush(msg: str) -> None:
    """Print a message and flush immediately so it appears in subprocess output."""
    print(msg, flush=True)


def _fill_keycloak_login(page: Page, username: str, password: str) -> None:
    """Fill Keycloak's single-page login form and handle optional TOTP."""
    _log = _print_flush
    _log(">>> Keycloak: waiting for login form ...")
    page.locator(_KC_SUBMIT).wait_for(timeout=_FORM_TIMEOUT)

    page.locator(_KC_USERNAME).fill(username)
    page.locator(_KC_PASSWORD).fill(password)
    page.locator(_KC_SUBMIT).click()
    _log(">>> Keycloak: credentials submitted.")

    # After submit, either we redirect back to the product (no MFA) or we
    # land on an OTP page.  Wait for either the OTP field to appear or for
    # the URL to leave the Keycloak domain (redirect back to product).
    _log(">>> Keycloak: checking for MFA challenge ...")
    otp_field = page.locator(_KC_OTP)
    try:
        otp_field.wait_for(state="visible", timeout=_MFA_DETECT_TIMEOUT)
    except PlaywrightTimeout:
        _log(">>> Keycloak: no MFA challenge detected, proceeding.")
        return

    _log(">>> Keycloak: TOTP input detected.")
    code = input(">>> Enter your verification code: ").strip()
    otp_field.fill(code)
    page.locator(_KC_SUBMIT).click()
    _log(">>> Keycloak: TOTP code submitted.")


def _fill_okta_login(page: Page, username: str, password: str) -> None:
    """Fill Okta's multi-step login form and handle optional MFA."""
    _log = _print_flush

    # Step 1: identifier page.
    _log(">>> Okta: waiting for identifier field ...")
    page.locator(_OKTA_IDENTIFIER).wait_for(timeout=_FORM_TIMEOUT)
    page.locator(_OKTA_IDENTIFIER).fill(username)
    page.locator(_OKTA_SUBMIT).first.click()
    _log(">>> Okta: identifier submitted.")

    # Step 2: password page.
    _log(">>> Okta: waiting for password field ...")
    page.locator(_OKTA_PASSCODE).wait_for(timeout=_FORM_TIMEOUT)
    page.locator(_OKTA_PASSCODE).fill(password)

    # Capture the current URL before submitting — Okta's login widget is a
    # SPA that keeps the authorize URL through identifier and password steps.
    # The URL only changes once Okta processes the credentials (either to an
    # MFA page or back to the product callback).
    pre_submit_url = page.url
    page.locator(_OKTA_SUBMIT).first.click()
    _log(">>> Okta: password submitted, waiting for navigation ...")

    # Step 3: wait for the URL to change from the authorize endpoint.
    try:
        page.wait_for_url(
            lambda url: url != pre_submit_url,
            timeout=30_000,
        )
    except PlaywrightTimeout:
        # URL didn't change — credentials may have failed.  Log what we see.
        _log(f">>> Okta: URL unchanged after password submit: {page.url}")
        _log(">>> Okta: page title: " + (page.title() or "(empty)"))
        # Check for an error message on the page.
        error = page.locator("[data-se='o-form-error-container'], .okta-form-infobox-error")
        if error.is_visible():
            _log(f">>> Okta: login error: {error.text_content()}")
        return

    current_url = page.url
    _log(f">>> Okta: post-password URL: {current_url}")

    # Check for MFA by looking at the URL and page content.
    mfa_url_patterns = ("/challenge", "/verify", "/mfa", "/factor")
    is_mfa = any(pattern in current_url.lower() for pattern in mfa_url_patterns)

    if not is_mfa:
        _log(">>> Okta: no MFA challenge detected, proceeding.")
        return

    _log(f">>> Okta: MFA challenge detected at {page.url}")

    # Determine MFA type from page content.
    totp_input = page.locator("input[name='credentials.passcode']")
    try:
        totp_input.wait_for(state="visible", timeout=_MFA_DETECT_TIMEOUT)
        _log(">>> Okta: TOTP input detected.")
        code = input(">>> Enter your verification code: ").strip()
        totp_input.fill(code)
        page.locator(_OKTA_SUBMIT).first.click()
        _log(">>> Okta: TOTP code submitted.")
    except PlaywrightTimeout:
        # Push notification or other factor — wait for user to approve.
        _log(">>> Okta: no TOTP input found — assuming push/other MFA factor.")
        print(">>> Approve the notification on your device, then press Enter.",
              flush=True)
        input()
        _log(">>> Okta: waiting for MFA approval redirect ...")
        page.wait_for_url(
            lambda url: "/challenge" not in url.lower(),
            timeout=_MFA_TIMEOUT,
        )


_IDP_STRATEGIES: dict[str, Callable[[Page, str, str], None]] = {
    "keycloak": _fill_keycloak_login,
    "okta": _fill_okta_login,
}

SUPPORTED_IDPS = frozenset(_IDP_STRATEGIES.keys())


def get_idp_strategy(idp: str) -> Callable[[Page, str, str], None]:
    """Return the form-filling function for the given IdP name.

    The *idp* value is normalized (stripped, lowercased) before lookup.
    Raises ``AuthConfigError`` if *idp* is not supported.
    """
    from vip.auth import AuthConfigError

    normalized = idp.strip().lower()
    strategy = _IDP_STRATEGIES.get(normalized)
    if strategy is None:
        supported = ", ".join(sorted(SUPPORTED_IDPS))
        raise AuthConfigError(f"Unsupported IdP {idp!r}. Supported: {supported}")
    return strategy
