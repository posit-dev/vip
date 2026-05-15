"""Generate TOTP codes from a shared secret for automated MFA flows.

Reads VIP_TEST_TOTP_SECRET (a base32-encoded TOTP seed) and produces
the current 6-digit code on demand. Designed for unattended runs
against dedicated test service accounts ONLY: the seed is equivalent
to bypassing 2FA for the account it belongs to.
"""

from __future__ import annotations

import os  # noqa: F401  (used by get_code in Task 3)

import pyotp

ENV_VAR = "VIP_TEST_TOTP_SECRET"


def validate_secret(secret: str) -> None:
    """Raise AuthConfigError if *secret* is not a usable base32 TOTP seed.

    Called from start_headless_auth before Playwright launches so a bad
    seed fails fast with a clear error instead of mid-login.
    """
    # Lazy import: auth.py imports this module, so a top-level import of
    # AuthConfigError would create a circular import. idp.py uses the
    # same pattern.
    from vip.auth import AuthConfigError

    if not secret:
        raise AuthConfigError(f"{ENV_VAR} is set but empty")
    try:
        pyotp.TOTP(secret).now()
    except Exception as exc:
        raise AuthConfigError(f"{ENV_VAR} is not a valid base32 TOTP seed: {exc}") from exc
