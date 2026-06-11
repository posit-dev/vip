"""IdP login form strategies for headless OIDC authentication.

Each strategy automates a specific identity provider's login form using
Playwright.  Strategies fill username/password and handle MFA prompting
via the terminal when the IdP presents a second-factor challenge.
"""

from __future__ import annotations

from collections.abc import Callable

from playwright.sync_api import Error, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from vip import totp
from vip.timeouts import scaled, timeout_scale

# Keycloak selectors — validated by PPM's e2e test suite.
_KC_USERNAME = "input[id='username']"
_KC_PASSWORD = "input[id='password']"
_KC_SUBMIT = "button[id='kc-login']"
_KC_OTP = "input[id='otp']"

# Okta selectors.
_OKTA_IDENTIFIER = "input[name='identifier']"
_OKTA_PASSCODE = "input[name='credentials.passcode']"
_OKTA_SUBMIT = "input[type='submit'], button[type='submit']"

# Snowflake OAuth selectors. Snowflake's sign-in page renders two
# "Sign in" buttons (a federated-SSO option and the username/password
# option); the username/password submit is the second one.
_SF_USERNAME = '[autocomplete="username"]'
_SF_PASSWORD = '[autocomplete="current-password"]'
_SF_SUBMIT = 'button:has-text("Sign in")'
_SF_ALLOW = "Allow"
# Posit Team products delegate OIDC to the controller, so reaching a product
# bounces through Snowflake OAuth more than once (product-host ingress, then
# controller-host). Fill up to this many sign-in forms per login.
_SF_MAX_FORMS = 3
# Time to let the OAuth redirect chain reach the next sign-in form (ms).
_SF_NEXT_FORM_TIMEOUT = 20_000
# Time to wait for an optional "Allow" consent screen (ms).
_SF_CONSENT_TIMEOUT = 5_000

# Timeout for waiting on form elements (ms) — scaled at definition time.
_FORM_TIMEOUT = int(15_000 * timeout_scale())
# Timeout for detecting whether MFA is required after login submit (ms) — scaled.
_MFA_DETECT_TIMEOUT = int(10_000 * timeout_scale())
# Timeout for MFA completion after user is prompted (ms).
# This is a human wait, not a server operation — deliberately not scaled.
_MFA_TIMEOUT = 300_000  # 5 minutes


def _print_flush(msg: str) -> None:
    """Print a message and flush immediately so it appears in subprocess output."""
    print(msg, flush=True)


# Module-level verbose flag, set by start_headless_auth before calling strategies.
_verbose = False


def _log_verbose(msg: str) -> None:
    """Print only when verbose mode is active."""
    if _verbose:
        _print_flush(msg)


def _sanitize_url(url: str) -> str:
    """Return origin + path, stripping query params that may contain secrets."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _fill_keycloak_login(page: Page, username: str, password: str) -> None:
    """Fill Keycloak's single-page login form and handle optional TOTP."""
    _log_verbose(">>> Keycloak: waiting for login form ...")
    page.locator(_KC_SUBMIT).wait_for(timeout=_FORM_TIMEOUT)

    page.locator(_KC_USERNAME).fill(username)
    page.locator(_KC_PASSWORD).fill(password)
    page.locator(_KC_SUBMIT).click()
    _log_verbose(">>> Keycloak: credentials submitted.")

    _log_verbose(">>> Keycloak: checking for MFA challenge ...")
    otp_field = page.locator(_KC_OTP)
    try:
        otp_field.wait_for(state="visible", timeout=_MFA_DETECT_TIMEOUT)
    except PlaywrightTimeout:
        _log_verbose(">>> Keycloak: no MFA challenge detected, proceeding.")
        return

    _log_verbose(">>> Keycloak: obtaining TOTP code ...")
    code = totp.get_code(">>> Enter your verification code: ")
    otp_field.fill(code)
    page.locator(_KC_SUBMIT).click()
    _log_verbose(">>> Keycloak: TOTP code submitted.")


def _select_totp_authenticator(page: Page) -> None:
    """If Okta shows an authenticator selection page, click the TOTP option.

    Okta Identity Engine may present a list of authenticators (TOTP,
    push, security key) after password verification.  This function
    looks for the "Enter a code" option and clicks its "Select" button
    to navigate to the TOTP input page.

    If the page is already showing a TOTP input (no selection needed),
    or there's no recognizable selection page, this function returns
    without action.
    """
    # Already on a TOTP input page? Nothing to do.
    passcode_inputs = page.locator("input[name='credentials.passcode']")
    for i in range(passcode_inputs.count()):
        if passcode_inputs.nth(i).is_visible():
            return

    # Look for the "Enter a code" authenticator option and click its
    # "Select" button.  We only click when we can confirm the button
    # belongs to the code-based option (not push or security key).

    # Strategy 1: Okta data attribute for the TOTP option container.
    code_option = page.locator("[data-se='authenticator-verify-list'] [data-se='okta_verify-totp']")
    if code_option.count() > 0:
        select_btn = code_option.get_by_role("link", name="Select")
        if select_btn.count() == 0:
            select_btn = code_option.get_by_role("button", name="Select")
        if select_btn.count() > 0 and select_btn.first.is_visible():
            _log_verbose(">>> Okta: selecting 'Enter a code' authenticator (data-se) ...")
            select_btn.first.click()
            page.wait_for_load_state("domcontentloaded")
            return

    # Strategy 2: Find visible "Enter a code" text, walk up to the
    # nearest list item, verify it still contains "Enter a code", then
    # click "Select" within that item only.
    code_texts = page.get_by_text("Enter a code", exact=False).all()
    for ct in code_texts:
        if not ct.is_visible():
            continue
        # Walk up to the nearest list item — each authenticator option
        # is typically an <li> or a div with an authenticator class.
        parent = ct.locator("xpath=ancestor::div[contains(@class,'authenticator')]")
        if parent.count() == 0:
            parent = ct.locator("xpath=ancestor::li[1]")
        if parent.count() == 0:
            continue
        container = parent.first
        # Verify this container is the one with "Enter a code" (not a
        # broader parent that also contains other authenticators).
        if "enter a code" not in (container.inner_text() or "").lower():
            continue
        select_link = container.get_by_role("link", name="Select")
        if select_link.count() == 0:
            select_link = container.get_by_role("button", name="Select")
        if select_link.count() > 0 and select_link.first.is_visible():
            _log_verbose(">>> Okta: selecting 'Enter a code' authenticator (text) ...")
            select_link.first.click()
            page.wait_for_load_state("domcontentloaded")
            return

    _log_verbose(">>> Okta: no authenticator selection page detected.")


def _fill_okta_login(page: Page, username: str, password: str) -> None:
    """Fill Okta's multi-step login form and handle optional MFA."""

    # Step 1: identifier page.
    _log_verbose(">>> Okta: waiting for identifier field ...")
    page.locator(_OKTA_IDENTIFIER).wait_for(timeout=_FORM_TIMEOUT)
    page.locator(_OKTA_IDENTIFIER).fill(username)
    page.locator(_OKTA_SUBMIT).first.click()
    _log_verbose(">>> Okta: identifier submitted.")

    # Step 2: password page.
    _log_verbose(">>> Okta: waiting for password field ...")
    page.locator(_OKTA_PASSCODE).wait_for(timeout=_FORM_TIMEOUT)
    page.locator(_OKTA_PASSCODE).fill(password)

    # Snapshot the current form state before clicking submit so we can
    # detect when the form transitions.  Okta's SPA often keeps the same
    # URL and reuses the same input fields between steps.
    submit_text_before = page.locator(_OKTA_SUBMIT).first.text_content() or ""
    heading_before = ""
    heading_el = page.locator("h2, [data-se='o-form-head']").first
    if heading_el.is_visible():
        heading_before = (heading_el.text_content() or "").lower().strip()

    page.locator(_OKTA_SUBMIT).first.click()
    _log_verbose(">>> Okta: password submitted, waiting for response ...")

    # Step 3: detect what happened after password submission.
    #
    # Okta's login widget is a SPA — the URL often does NOT change
    # between steps.  The TOTP MFA step reuses the same
    # input[name='credentials.passcode'] field.  We poll for state
    # changes by comparing against the pre-submit snapshot.
    import time as _time

    from vip.auth import AuthConfigError

    pre_submit_url = page.url
    deadline = _time.monotonic() + 30

    error_selectors = (
        "[data-se='o-form-error-container'],.okta-form-infobox-error,[class*='error-message']"
    )
    mfa_selectors = (
        "[data-se='authenticator-verify-list'],"
        "[data-se='okta_verify-push'],"
        "[data-se='google_otp'],"
        "[class*='authenticator-button'],"
        "[data-se='phone_number']"
    )

    while _time.monotonic() < deadline:
        try:
            # Check: URL changed (redirect to product).
            if page.url != pre_submit_url:
                _log_verbose(f">>> Okta: URL changed to: {_sanitize_url(page.url)}")
                break

            # Check: error banner visible.
            for sel in error_selectors.split(","):
                loc = page.locator(sel.strip())
                if loc.count() > 0 and loc.first.is_visible():
                    error_msg = (loc.first.text_content() or "").strip()
                    _log_verbose(f">>> Okta: login error: {error_msg}")
                    raise AuthConfigError(f"Okta login failed: {error_msg}")

            # Check: MFA-specific elements appeared.
            for sel in mfa_selectors.split(","):
                loc = page.locator(sel.strip())
                if loc.count() > 0 and loc.first.is_visible():
                    _log_verbose(">>> Okta: MFA authenticator elements detected.")
                    break
            else:
                # Check: submit button text changed (form transitioned).
                submit_loc = page.locator(_OKTA_SUBMIT).first
                submit_text_now = ""
                if submit_loc.count() > 0:
                    submit_text_now = submit_loc.text_content() or ""
                if submit_text_now and submit_text_now != submit_text_before:
                    _log_verbose(f">>> Okta: form transitioned (button: {submit_text_now!r})")
                    break

                # Check: heading changed (form transitioned to a new step).
                heading_now = ""
                if heading_el.count() > 0 and heading_el.is_visible():
                    heading_now = (heading_el.text_content() or "").lower().strip()
                if heading_now and heading_now != heading_before:
                    _log_verbose(f">>> Okta: heading changed to: {heading_now!r}")
                    break

                page.wait_for_timeout(500)
                continue
            break  # MFA selector loop broke — exit outer loop too
        except AuthConfigError:
            raise
        except (PlaywrightTimeout, Error):
            # Transient Playwright error during widget transition — retry.
            page.wait_for_timeout(500)
    else:
        _log_verbose(f">>> Okta: no state change after 30s: {_sanitize_url(page.url)}")
        raise AuthConfigError(
            "Okta login did not respond after password submission. "
            "Check credentials and IdP configuration."
        )

    _log_verbose(f">>> Okta: password accepted. URL: {_sanitize_url(page.url)}")

    # Determine whether we're in an MFA flow or already redirecting.
    current_url = page.url.lower()
    mfa_url_patterns = ("/challenge", "/verify", "/mfa", "/factor")
    url_has_mfa = any(p in current_url for p in mfa_url_patterns)

    mfa_content = page.locator(f"{mfa_selectors},input[name='credentials.passcode']")
    has_mfa_content = mfa_content.first.is_visible()

    if not url_has_mfa and not has_mfa_content:
        _log_verbose(">>> Okta: no MFA challenge detected, proceeding.")
        return

    _log_verbose(f">>> Okta: MFA challenge detected at {_sanitize_url(page.url)}")

    # Handle authenticator selection page — Okta may present a list of
    # MFA options (TOTP, push, security key).  Click "Select" next to
    # the code-based option to get to the TOTP input.
    _select_totp_authenticator(page)

    # Wait for the page to settle after authenticator selection.
    try:
        page.wait_for_load_state("networkidle", timeout=int(scaled(10_000)))
    except PlaywrightTimeout:
        pass

    # Now wait for the TOTP input to appear.  Try each selector in
    # priority order and use the first one that becomes visible.
    totp_selectors = (
        "input[name='credentials.passcode']",
        "input[name='credentials.totp']",
        "input[autocomplete='one-time-code']",
        "input[data-se='credentials.passcode']",
    )
    totp_field = None
    deadline_totp = _time.monotonic() + _MFA_DETECT_TIMEOUT / 1000
    while _time.monotonic() < deadline_totp:
        for sel in totp_selectors:
            loc = page.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                totp_field = loc.first
                break
        if totp_field:
            break
        page.wait_for_timeout(500)

    if totp_field:
        _log_verbose(">>> Okta: TOTP input detected.")
        totp_field.clear()
        code = totp.get_code(">>> Enter your verification code: ")
        _log_verbose(">>> Okta: filling TOTP code ...")
        totp_field.fill(code)
        _log_verbose(">>> Okta: clicking verify ...")
        page.locator(_OKTA_SUBMIT).first.click()
        _log_verbose(">>> Okta: TOTP code submitted.")
    else:
        # No TOTP input after selection — fall back to push/wait.
        _log_verbose(">>> Okta: no TOTP input found — assuming push/other MFA factor.")
        print(">>> Approve the notification on your device, then press Enter.", flush=True)
        input()
        _log_verbose(">>> Okta: waiting for MFA approval redirect ...")
        page.wait_for_url(
            lambda url: "/challenge" not in url.lower(),
            timeout=_MFA_TIMEOUT,
        )


def _fill_snowflake_login(page: Page, username: str, password: str) -> None:
    """Drive Snowflake OAuth for a Posit Team Native App deployment.

    Each product (Connect, Workbench, Package Manager) sits behind a Snowpark
    Container Services ingress and delegates OIDC to the deployment's
    controller, which is itself behind the ingress. Reaching a product
    therefore bounces through Snowflake's OAuth flow (on
    ``*.snowflakecomputing.com``) more than once: first for the product
    host's ingress, then again for the controller host. Each hop presents the
    same Snowflake sign-in form, and the first authorization of an OAuth
    client also shows an "Allow" consent.

    This fills every sign-in form in the chain, waiting for each hop's
    navigation to settle before looking for the next, until the flow leaves
    Snowflake. It does *not* wait for the product page itself to finish
    loading — ``_wait_for_product_redirect`` in ``vip.auth`` handles that.
    """
    for attempt in range(_SF_MAX_FORMS):
        # Give the first form the normal timeout; later hops a longer one,
        # since the OAuth chain takes several redirects to reach them.
        timeout = _FORM_TIMEOUT if attempt == 0 else _SF_NEXT_FORM_TIMEOUT
        try:
            page.locator(_SF_USERNAME).wait_for(state="visible", timeout=timeout)
        except PlaywrightTimeout:
            # No (further) sign-in form — the chain has moved past Snowflake login.
            _log_verbose(f">>> Snowflake: no sign-in form after {attempt} fill(s); done.")
            break

        before = page.url
        page.locator(_SF_USERNAME).fill(username)
        page.locator(_SF_PASSWORD).fill(password)
        # The username/password "Sign in" button is the second one on the page.
        page.locator(_SF_SUBMIT).nth(1).click()
        _log_verbose(f">>> Snowflake: submitted sign-in form #{attempt + 1}.")

        # The first authorization of an OAuth client shows an "Allow" consent.
        try:
            allow_button = page.get_by_role("button", name=_SF_ALLOW)
            allow_button.wait_for(state="visible", timeout=_SF_CONSENT_TIMEOUT)
            allow_button.click()
            _log_verbose(">>> Snowflake: clicked 'Allow' consent.")
        except (PlaywrightTimeout, Error):
            pass

        # Let the OAuth redirect chain advance to the next hop before looking
        # for another form. Filling without waiting for navigation races the
        # redirect and re-submits a stale form, which stalls the flow.
        # (Named, typed predicate rather than a lambda so mypy can type it; the
        # ``_before`` default snapshots this hop's URL — also avoids closing over
        # the loop variable.)
        def url_advanced(url: str, _before: str = before) -> bool:
            return url != _before

        try:
            page.wait_for_url(url_advanced, timeout=_SF_NEXT_FORM_TIMEOUT)
        except (PlaywrightTimeout, Error):
            pass


_IDP_STRATEGIES: dict[str, Callable[[Page, str, str], None]] = {
    "keycloak": _fill_keycloak_login,
    "okta": _fill_okta_login,
    "snowflake": _fill_snowflake_login,
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
