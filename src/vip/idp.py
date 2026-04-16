"""IdP login form strategies for headless OIDC authentication.

Each strategy automates a specific identity provider's login form using
Playwright.  Strategies fill username/password and handle MFA prompting
via the terminal when the IdP presents a second-factor challenge.
"""

from __future__ import annotations

from collections.abc import Callable

from playwright.sync_api import Page

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
# Timeout for MFA completion after user is prompted (ms).
_MFA_TIMEOUT = 300_000  # 5 minutes


def _fill_keycloak_login(page: Page, username: str, password: str) -> None:
    """Fill Keycloak's single-page login form and handle optional TOTP."""
    page.locator(_KC_SUBMIT).wait_for(timeout=_FORM_TIMEOUT)

    page.locator(_KC_USERNAME).fill(username)
    page.locator(_KC_PASSWORD).fill(password)
    page.locator(_KC_SUBMIT).click()

    # After submit, either we redirect back to the product (no MFA) or we
    # land on an OTP page.  Wait briefly for either state.
    page.wait_for_load_state("domcontentloaded")

    otp_field = page.locator(_KC_OTP)
    if otp_field.is_visible():
        code = input(">>> Enter your verification code: ").strip()
        otp_field.fill(code)
        page.locator(_KC_SUBMIT).click()


def _fill_okta_login(page: Page, username: str, password: str) -> None:
    """Fill Okta's multi-step login form and handle optional MFA."""
    # Step 1: identifier page.
    page.locator(_OKTA_IDENTIFIER).wait_for(timeout=_FORM_TIMEOUT)
    page.locator(_OKTA_IDENTIFIER).fill(username)
    page.locator(_OKTA_SUBMIT).first.click()

    # Step 2: password page.
    page.locator(_OKTA_PASSCODE).wait_for(timeout=_FORM_TIMEOUT)
    page.locator(_OKTA_PASSCODE).fill(password)
    page.locator(_OKTA_SUBMIT).first.click()

    # Step 3: check for MFA challenge.
    page.wait_for_load_state("domcontentloaded")

    if "/challenge" in page.url.lower():
        # Determine MFA type from page content.
        totp_input = page.locator("input[name='credentials.passcode']")
        if totp_input.is_visible():
            code = input(">>> Enter your verification code: ").strip()
            totp_input.fill(code)
            page.locator(_OKTA_SUBMIT).first.click()
        else:
            # Push notification or other factor — wait for user to approve.
            print(">>> Approve the notification on your device, then press Enter.")
            input()
            # The page should auto-redirect after approval.  Give it time.
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

    Raises ``ValueError`` if *idp* is not supported.
    """
    strategy = _IDP_STRATEGIES.get(idp)
    if strategy is None:
        supported = ", ".join(sorted(SUPPORTED_IDPS))
        raise ValueError(f"Unsupported IdP {idp!r}. Supported: {supported}")
    return strategy
