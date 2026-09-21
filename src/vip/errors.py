"""VIP's exception hierarchy for user-facing CLI failures.

Every :class:`VipError` carries an ``exit_code`` so the CLI's single exit
handler (``cli.main``'s ``args.func(args)`` dispatch) can print the message
and exit with the right code, instead of each command function calling
``sys.exit`` itself.
"""

from __future__ import annotations


class VipError(Exception):
    """Base class for VIP errors that should exit the CLI cleanly.

    Raise a subclass (or this class directly) instead of calling
    ``sys.exit`` from command code -- ``cli.main``'s dispatch catches it,
    prints the message, and exits with ``exit_code``.
    """

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class ConfigError(VipError):
    """Raised for invalid CLI flags or ``vip.toml`` configuration."""


class AuthError(VipError):
    """Raised when authenticating to a product fails."""


class ProductUnreachableError(VipError):
    """Raised when a product API call fails or the product cannot be reached."""


class InstallError(VipError):
    """Raised when installing or uninstalling system or Playwright dependencies fails."""


class ReportError(VipError):
    """Raised when rendering or reading a VIP report fails."""


class AuthConfigError(AuthError):
    """Raised for user-facing authentication configuration errors."""


class AuthTimeoutError(AuthConfigError):
    """Raised when a login round-trip does not complete before its deadline.

    A subclass of :class:`AuthConfigError` so ``plugin.py``'s existing
    ``except AuthConfigError`` handler (which converts it to a clean
    ``pytest.UsageError`` rather than an ``INTERNALERROR`` traceback) picks
    this up too, with no change to that handler required. See #263.
    """
