"""IdP login form strategies for headless OIDC authentication.

Each strategy automates a specific identity provider's login form using
Playwright.  Strategies fill username/password and handle MFA prompting
via the terminal when the IdP presents a second-factor challenge.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from urllib.parse import urlparse

from playwright.sync_api import Error, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from vip import totp
from vip.errors import AuthConfigError
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
    pre_submit_url = page.url
    deadline = time.monotonic() + 30

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

    while time.monotonic() < deadline:
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
    deadline_totp = time.monotonic() + _MFA_DETECT_TIMEOUT / 1000
    while time.monotonic() < deadline_totp:
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


# Entra ID (Azure AD) selectors -- not yet validated against a live tenant.
# Microsoft has been rolling out a refreshed sign-in UI, so treat these as a
# starting point to confirm/adjust from the first real run.
_ENTRA_USERNAME = "input[name='loginfmt']"
_ENTRA_PASSWORD = "input[name='passwd']"
# #idSIButton9 is Entra's single primary button, reused on every step
# (Next / Sign in / Yes) -- safe to click to submit, but never usable to
# detect which step is currently showing.
_ENTRA_SUBMIT = "#idSIButton9"
_ENTRA_USERNAME_ERROR = "#usernameError"
_ENTRA_PASSWORD_ERROR = "#passwordError"
_ENTRA_SERVICE_ERROR = "#service_exception_message, #serviceExceptionMessage"
# Conditional Access block page ("You can't get there from here"): a
# full-page error rather than a field-level one, so it's detected by text
# instead of an inline-error selector. Can appear right after the email
# step or after MFA, so it's checked wherever _raise_if_entra_error is.
_ENTRA_CONDITIONAL_ACCESS_HEADING = "You can't get there from here"
_ENTRA_CONDITIONAL_ACCESS_CODES = ("AADSTS53000", "AADSTS53003")
_ENTRA_OTC_INPUT = "input[name='otc'], #idTxtBx_SAOTCC_OTC"
_ENTRA_OTC_SUBMIT = "#idSubmit_SAOTCC_Continue"
# "Use a verification code" option on Entra's "Verify your identity" method list.
_ENTRA_VERIFY_CODE_OPTION = "[data-value='PhoneAppOTP']"
# Number shown during an Authenticator push with number matching enabled.
_ENTRA_DISPLAY_SIGN = "#idRichContext_DisplaySign"
# Fallback text for a plain push (no number matching) when the above is absent.
_ENTRA_PUSH_TEXT = "notification"
# Link Entra shows on an auto-sent push screen to reach the method list instead.
_ENTRA_SIGN_IN_ANOTHER_WAY = "#signInAnotherWay"
# "More information required" proof-up / MFA-registration interrupt heading.
_ENTRA_PROOF_UP_TEXT = "More information required"
# KMSI ("Stay signed in?") markers and its "No" button.
_ENTRA_KMSI_MARKER = "input[name='DontShowAgain'], #KmsiCheckboxField"
_ENTRA_KMSI_NO = "#idBtn_Back"
# Entra login hosts across the public cloud and sovereign/alt clouds (US
# Government, China). A host outside this set means the tenant redirected to
# a federated IdP, not just a different Microsoft cloud.
_ENTRA_LOGIN_HOSTS = frozenset(
    {
        "login.microsoftonline.com",
        "login.microsoftonline.us",
        "login.partner.microsoftonline.cn",
        "login.chinacloudapi.cn",
        "login.microsoft.com",
    }
)


def _entra_login_host(page: Page) -> str:
    """Return the lowercased hostname of the current page URL."""
    return (urlparse(page.url).hostname or "").lower()


def _entra_left_login_host(page: Page) -> bool:
    """True once the browser has navigated away from a known Entra login host.

    Matches on the parsed hostname, not a substring of the whole URL, so a
    query parameter that happens to contain a login host's name can't cause
    a false negative.
    """
    return _entra_login_host(page) not in _ENTRA_LOGIN_HOSTS


def _entra_conditional_access_code(page: Page) -> str:
    """Return the visible Conditional Access error code (e.g. "AADSTS53000"),
    or "" if neither known code is shown on the page.
    """
    for code in _ENTRA_CONDITIONAL_ACCESS_CODES:
        loc = page.get_by_text(code, exact=False)
        if loc.count() > 0 and loc.first.is_visible():
            return code
    return ""


def _raise_if_entra_error(page: Page) -> None:
    """Raise AuthConfigError if Entra is showing an inline error message or
    a Conditional Access block page.
    """
    # Check Conditional Access first: its block page can also carry a generic
    # service-exception message, which would hide the actionable cause.
    code = _entra_conditional_access_code(page)
    heading = page.get_by_text(_ENTRA_CONDITIONAL_ACCESS_HEADING, exact=False)
    if code or (heading.count() > 0 and heading.first.is_visible()):
        detail = f" ({code})" if code else ""
        raise AuthConfigError(
            f"Entra Conditional Access blocked this sign-in{detail}. Headless "
            "auth runs in an unmanaged browser, so use a test service account "
            "excluded from device-compliance / Conditional Access policies."
        )

    for sel in (_ENTRA_USERNAME_ERROR, _ENTRA_PASSWORD_ERROR, _ENTRA_SERVICE_ERROR):
        loc = page.locator(sel)
        if loc.count() > 0 and loc.first.is_visible():
            msg = (loc.first.text_content() or "").strip()
            if msg:
                raise AuthConfigError(f"Entra login failed: {msg}")


def _entra_is_proof_up(page: Page) -> bool:
    """True if Entra is showing a "More information required" proof-up /
    MFA-registration interrupt -- this can't be automated; the test
    account must already have MFA registered.
    """
    heading = page.get_by_text(_ENTRA_PROOF_UP_TEXT, exact=False)
    return heading.count() > 0 and heading.first.is_visible()


def _select_entra_totp_method(page: Page) -> bool:
    """If Entra shows a "Verify your identity" authenticator list, select
    "Use a verification code" and return True. Returns False when no such
    list is showing (already on an input, or a different challenge).

    Mirrors ``_select_totp_authenticator``'s caution for Okta: only clicks
    when the option can be confirmed as the code-based one, not push or a
    phone call.
    """
    option = page.locator(_ENTRA_VERIFY_CODE_OPTION)
    if option.count() > 0 and option.first.is_visible():
        _log_verbose(">>> Entra: selecting 'Use a verification code' option ...")
        option.first.click()
        return True

    text_option = page.get_by_text("Use a verification code", exact=False)
    for i in range(text_option.count()):
        candidate = text_option.nth(i)
        if candidate.is_visible():
            _log_verbose(">>> Entra: selecting 'Use a verification code' option (text) ...")
            candidate.click()
            return True
    return False


def _entra_handle_otc(page: Page) -> None:
    """Fill and submit a verification-code (TOTP) prompt."""
    _log_verbose(">>> Entra: verification-code prompt detected.")
    code = totp.get_code(">>> Enter your verification code: ")
    page.locator(_ENTRA_OTC_INPUT).first.fill(code)
    submit = page.locator(_ENTRA_OTC_SUBMIT)
    if submit.count() > 0 and submit.first.is_visible():
        submit.first.click()
    else:
        page.locator(_ENTRA_SUBMIT).click()
    _log_verbose(">>> Entra: verification code submitted.")


def _entra_is_push(page: Page) -> bool:
    """True if Entra is showing an Authenticator push-approval screen,
    with or without number matching.
    """
    display = page.locator(_ENTRA_DISPLAY_SIGN)
    if display.count() > 0 and display.first.is_visible():
        return True
    text = page.get_by_text(_ENTRA_PUSH_TEXT, exact=False)
    return text.count() > 0 and text.first.is_visible()


def _entra_try_switch_from_push(page: Page) -> bool:
    """Try to leave an auto-sent push prompt for the method list instead.

    Entra can send a push automatically when it's the account's default
    method, which would otherwise block an unattended run for up to
    ``_MFA_TIMEOUT`` waiting for approval nobody will give. Only relevant
    when VIP_TEST_TOTP_SECRET is set (a code can be generated unattended);
    without it, the existing push wait is the only option. Returns True if
    the "sign in another way" link was clicked, False if Entra didn't offer
    one -- callers should fall back to waiting on the push as before.
    """
    if not os.environ.get(totp.ENV_VAR, "").strip():
        return False

    link = page.locator(_ENTRA_SIGN_IN_ANOTHER_WAY)
    if link.count() > 0 and link.first.is_visible():
        _log_verbose(">>> Entra: switching away from auto-sent push to pick a code ...")
        link.first.click()
        return True

    text_link = page.get_by_text("Sign in another way", exact=False)
    for i in range(text_link.count()):
        candidate = text_link.nth(i)
        if candidate.is_visible():
            _log_verbose(">>> Entra: switching away from auto-sent push (text) ...")
            candidate.click()
            return True
    return False


def _entra_handle_push(page: Page) -> None:
    """Print the approval prompt (with the displayed number, if number
    matching is enabled) and wait for the push to be approved on-device.
    """
    display = page.locator(_ENTRA_DISPLAY_SIGN)
    if display.count() > 0 and display.first.is_visible():
        number = (display.first.text_content() or "").strip()
        print(
            f">>> Enter {number} in Microsoft Authenticator to approve sign-in.",
            flush=True,
        )
    else:
        print(
            ">>> Approve the sign-in request in Microsoft Authenticator, then wait.",
            flush=True,
        )
    _log_verbose(">>> Entra: waiting for push approval ...")
    before = page.url

    def _advanced(url: str, _before: str = before) -> bool:
        return url != _before

    page.wait_for_url(_advanced, timeout=_MFA_TIMEOUT)


def _entra_is_kmsi(page: Page) -> bool:
    """True if Entra is showing the "Stay signed in?" (KMSI) prompt."""
    marker = page.locator(_ENTRA_KMSI_MARKER)
    if marker.count() > 0 and marker.first.is_visible():
        return True
    return "/kmsi" in page.url.lower()


def _entra_dismiss_kmsi(page: Page) -> None:
    """Click "No" on the "Stay signed in?" (KMSI) prompt, if shown.

    Clicking "Yes" plants a persistent ESTS refresh cookie into the storage
    state VIP writes to the auth cache on disk; "No" keeps the cached
    session to what Playwright's storage_state already captures. KMSI is
    optional (some tenants disable it), so its absence is not an error.
    """
    no_button = page.locator(_ENTRA_KMSI_NO)
    if no_button.count() > 0 and no_button.first.is_visible():
        _log_verbose(">>> Entra: dismissing 'Stay signed in?' with No ...")
        no_button.first.click()


def _entra_resolve_post_password(page: Page) -> None:
    """After password submit, resolve whatever Entra shows next.

    Polls (bounded by ``_MFA_DETECT_TIMEOUT``) for one of: an inline
    error, a proof-up registration interrupt, MFA (verification code,
    method selection, or Authenticator push), the KMSI prompt, or simply
    leaving Entra's login host because no further challenge applies.
    """
    deadline = time.monotonic() + _MFA_DETECT_TIMEOUT / 1000
    mfa_handled = False
    while time.monotonic() < deadline:
        if _entra_left_login_host(page):
            _log_verbose(f">>> Entra: left login host: {_sanitize_url(page.url)}")
            return

        _raise_if_entra_error(page)

        if _entra_is_proof_up(page):
            raise AuthConfigError(
                "Entra requires additional security-info registration "
                "('More information required') for this account before "
                "signing in. Register MFA on the test service account "
                "ahead of time -- this interrupt cannot be automated."
            )

        if not mfa_handled:
            otc_field = page.locator(_ENTRA_OTC_INPUT)
            if otc_field.count() > 0 and otc_field.first.is_visible():
                _entra_handle_otc(page)
                mfa_handled = True
                # totp.get_code can block on a human prompt, so the original
                # deadline may already be gone -- recompute it from now or
                # KMSI below would never get a chance to run.
                deadline = time.monotonic() + _MFA_DETECT_TIMEOUT / 1000
                continue

            if _select_entra_totp_method(page):
                page.wait_for_timeout(500)
                continue

            if _entra_is_push(page):
                if _entra_try_switch_from_push(page):
                    page.wait_for_timeout(500)
                    continue
                _entra_handle_push(page)
                mfa_handled = True
                # Push approval is a human wait (up to _MFA_TIMEOUT) -- same
                # deadline-reset reasoning as the TOTP branch above.
                deadline = time.monotonic() + _MFA_DETECT_TIMEOUT / 1000
                continue

        if _entra_is_kmsi(page):
            _entra_dismiss_kmsi(page)
            page.wait_for_timeout(300)
            continue

        page.wait_for_timeout(300)

    _log_verbose(">>> Entra: no further challenge detected within timeout; proceeding.")


def _fill_entra_login(page: Page, username: str, password: str) -> None:
    """Fill Microsoft Entra ID's multi-step login form and handle MFA/KMSI.

    Entra serves each step as a full page from login.microsoftonline.com:
    email, password, then an optional MFA challenge and/or "Stay signed
    in?" (KMSI) prompt. A federated tenant instead redirects away from
    login.microsoftonline.com right after the email step -- that case
    raises ``AuthConfigError`` pointing at configuring the federated IdP
    directly, rather than hanging until timeout.
    """
    _log_verbose(">>> Entra: waiting for email field ...")
    page.locator(_ENTRA_USERNAME).wait_for(timeout=_FORM_TIMEOUT)
    page.locator(_ENTRA_USERNAME).fill(username)
    page.locator(_ENTRA_SUBMIT).click()
    _log_verbose(">>> Entra: email submitted.")

    _log_verbose(">>> Entra: waiting for password field ...")
    password_field = page.locator(_ENTRA_PASSWORD)
    deadline = time.monotonic() + _FORM_TIMEOUT / 1000
    while time.monotonic() < deadline:
        if password_field.count() > 0 and password_field.first.is_visible():
            break
        _raise_if_entra_error(page)
        if _entra_left_login_host(page):
            raise AuthConfigError(
                "Entra sign-in redirected to "
                f"{_sanitize_url(page.url)} -- this tenant is federated to "
                "another identity provider. Configure that IdP directly "
                '(e.g. idp = "okta") instead of idp = "entra".'
            )
        page.wait_for_timeout(300)
    else:
        raise AuthConfigError(
            "Entra login did not show a password field after the email "
            "step. Check credentials and IdP configuration, or rerun "
            "with --verbose."
        )

    password_field.first.fill(password)
    page.locator(_ENTRA_SUBMIT).click()
    _log_verbose(">>> Entra: password submitted.")

    _entra_resolve_post_password(page)


_IDP_STRATEGIES: dict[str, Callable[[Page, str, str], None]] = {
    "keycloak": _fill_keycloak_login,
    "okta": _fill_okta_login,
    "snowflake": _fill_snowflake_login,
    "entra": _fill_entra_login,
}

SUPPORTED_IDPS = frozenset(_IDP_STRATEGIES.keys())


def get_idp_strategy(idp: str) -> Callable[[Page, str, str], None]:
    """Return the form-filling function for the given IdP name.

    The *idp* value is normalized (stripped, lowercased) before lookup.
    Raises ``AuthConfigError`` if *idp* is not supported.
    """
    normalized = idp.strip().lower()
    strategy = _IDP_STRATEGIES.get(normalized)
    if strategy is None:
        supported = ", ".join(sorted(SUPPORTED_IDPS))
        raise AuthConfigError(f"Unsupported IdP {idp!r}. Supported: {supported}")
    return strategy
