"""VIP's command-line options."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register VIP's command-line options for config, auth mode, and reporting."""
    group = parser.getgroup("vip", "Verified Installation of Posit")
    group.addoption(
        "--vip-config",
        default=None,
        help="Path to vip.toml configuration file.",
    )
    group.addoption(
        "--vip-allow-unproven",
        action="store_true",
        default=False,
        help=(
            "Exit 0 even when checks went unproven (could not be verified). "
            "Restores the pre-attestation behaviour where an unverified check "
            "was indistinguishable from a passing run."
        ),
    )
    group.addoption(
        "--vip-extensions",
        action="append",
        default=[],
        help="Additional directories containing custom VIP test cases (repeatable).",
    )
    group.addoption(
        "--vip-report",
        default="report/results.json",
        help="Write a JSON results file at this path for Quarto report generation."
        " Set to empty string to disable. (default: report/results.json)",
    )
    group.addoption(
        "--vip-format",
        default="json",
        help="Comma-separated output formats: json,junit,sarif. json (results.json)"
        " is always written; junit/sarif are added as siblings. (default: json)",
    )
    group.addoption(
        "--interactive-auth",
        action="store_true",
        default=False,
        help="Launch a browser for manual OIDC login before running tests.",
    )
    group.addoption(
        "--headless-auth",
        action="store_true",
        default=False,
        help="Automate login in a headless browser (OIDC/SAML/OAuth2 requires [auth] idp).",
    )
    group.addoption(
        "--no-auth",
        action="store_true",
        default=False,
        help="Skip all tests that require authentication credentials (Connect and Workbench).",
    )
    group.addoption(
        "--api-auth",
        action="store_true",
        default=False,
        help="Run only API-key-authenticated tests; skip tests that require browser credentials.",
    )
    group.addoption(
        "--vip-verbose",
        action="store_true",
        default=False,
        help="Show full pytest tracebacks instead of concise error messages.",
    )
