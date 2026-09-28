"""Argument parser construction and the ``vip`` entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vip import __version__
from vip.cli.auth import mint_connect_key
from vip.cli.cleanup import run_cleanup
from vip.cli.install import run_install, run_uninstall
from vip.cli.report import run_report
from vip.cli.scaffold import _DEFAULT_SCAFFOLD_TEMPLATE, run_scaffold
from vip.cli.status import run_status
from vip.cli.verify import _IDP_PROVIDERS, DEFAULT_TEST_TIMEOUT_SECONDS, run_verify
from vip.cli.version import run_version
from vip.errors import VipError


def _reorder_help_args(argv: list[str], commands: set[str]) -> list[str]:
    """Let ``vip -h verify`` show verify's help instead of the top-level help.

    argparse's top-level parser consumes ``-h``/``--help`` before it delegates to
    a subparser, so a help flag placed *before* the subcommand prints the generic
    help. If a help flag appears ahead of a known subcommand, move it after the
    subcommand so the subparser handles it and prints its own help.
    """
    help_flags = {"-h", "--help"}
    first_help = next((i for i, a in enumerate(argv) if a in help_flags), None)
    if first_help is None:
        return argv
    first_cmd = next((i for i, a in enumerate(argv) if a in commands), None)
    if first_cmd is None or first_help > first_cmd:
        # No subcommand (top-level help is correct) or help already after it.
        return argv
    reordered = [a for a in argv if a not in help_flags]
    # Insert the help flag before any ``--`` passthrough separator. After ``--``
    # argparse treats every token as a positional, so an appended ``--help``
    # would be swallowed as a pytest arg and the command would run instead of
    # printing help.
    insert_at = reordered.index("--") if "--" in reordered else len(reordered)
    reordered.insert(insert_at, "--help")
    return reordered


def main() -> None:
    """Main entry point for the VIP CLI."""
    parser = argparse.ArgumentParser(
        prog="vip", description="VIP verification and credential tools"
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Print the vip version and exit",
    )
    subparsers = parser.add_subparsers(dest="command")

    # vip version
    version_parser = subparsers.add_parser(
        "version",
        help="Print the vip version and the minimum supported Posit Team version",
    )
    version_parser.set_defaults(func=run_version)

    # vip auth
    auth_parser = subparsers.add_parser("auth", help="Authentication tools")
    auth_sub = auth_parser.add_subparsers(dest="auth_command")

    # vip auth mint-connect-key
    mint_parser = auth_sub.add_parser(
        "mint-connect-key",
        help="Mint a Connect API key via interactive browser login",
    )
    mint_parser.add_argument("--url", required=True, help="Connect server URL")
    mint_parser.set_defaults(func=mint_connect_key)

    # vip verify
    verify_parser = subparsers.add_parser(
        "verify",
        help="Run VIP tests against a Posit Team deployment",
        description=(
            "Run VIP tests against a Posit Team deployment.\n\n"
            "Quick start (no config file needed):\n"
            "  vip verify --connect-url https://connect.example.com\n\n"
            "A browser window opens for authentication. After login,\n"
            "tests run headlessly and the browser session is cleaned up.\n\n"
            "With an existing config file:\n"
            "  vip verify --config vip.toml --no-interactive-auth\n\n"
            "Filter tests by name:\n"
            "  vip verify --connect-url https://connect.example.com --filter 'login'\n\n"
            "Any arguments after -- are passed directly to pytest:\n"
            "  vip verify --connect-url https://connect.example.com -- -x"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # URL args (no config file needed)
    url_group = verify_parser.add_argument_group("product URLs (no config file needed)")
    url_group.add_argument("--connect-url", default=None, help="Connect server URL")
    url_group.add_argument("--workbench-url", default=None, help="Workbench server URL")
    url_group.add_argument("--package-manager-url", default=None, help="Package Manager server URL")
    url_group.add_argument(
        "--connect-version",
        default=None,
        help=(
            "Deployed Connect version (e.g. 2026.06.0). Required for tests with a "
            "min_version marker to run instead of being skipped as N/A-by-version."
        ),
    )
    url_group.add_argument(
        "--workbench-version",
        default=None,
        help=(
            "Deployed Workbench version (e.g. 2026.06.0). Required for tests with a "
            "min_version marker to run instead of being skipped as N/A-by-version."
        ),
    )
    url_group.add_argument(
        "--package-manager-version",
        default=None,
        help=(
            "Deployed Package Manager version (e.g. 2026.06.0). Required for tests with a "
            "min_version marker to run instead of being skipped as N/A-by-version."
        ),
    )

    # TLS configuration
    tls_group = verify_parser.add_argument_group("TLS configuration")
    tls_group.add_argument(
        "--insecure",
        action="store_true",
        default=False,
        help=(
            "Disable TLS certificate verification (equivalent to curl -k). "
            "Use only in trusted environments; this silently ignores certificate errors. "
            "For Playwright browser contexts, this sets ignore_https_errors=True. "
            "Note: --ca-bundle is preferred when you have a custom CA certificate."
        ),
    )
    tls_group.add_argument(
        "--ca-bundle",
        default=None,
        metavar="PATH",
        type=Path,
        help=(
            "Path to a custom CA certificate bundle (PEM) to trust. "
            "Useful for self-signed or corporate CAs. "
            "For Playwright, sets NODE_EXTRA_CA_CERTS before launching Chromium "
            "(Chromium-level trust only; does not update the OS certificate store)."
        ),
    )

    # Proxy configuration
    proxy_group = verify_parser.add_argument_group("outbound proxy")
    proxy_group.add_argument(
        "--proxy",
        default=None,
        metavar="URL",
        help=(
            "Route outbound HTTP(S) through this proxy (e.g. http://proxy:8080). "
            "Applies to the product API clients, the auth/probe requests, and the "
            "Playwright browser login. Overrides HTTP_PROXY/HTTPS_PROXY, and also "
            "supersedes any NO_PROXY in the environment (repeat bypass hosts with "
            "--no-proxy). Only takes effect alongside the product-URL flags; it is "
            "ignored on a run that loads a config file, whether via --config or a "
            "./vip.toml (use a [proxy] section there instead). When omitted, VIP "
            "reads the ambient HTTP_PROXY/HTTPS_PROXY/NO_PROXY environment (same "
            "as httpx)."
        ),
    )
    proxy_group.add_argument(
        "--no-proxy",
        default=None,
        metavar="HOSTS",
        help=(
            "Comma-separated hosts to reach directly, bypassing --proxy "
            "(e.g. localhost,.internal.example). With no --proxy, passing an "
            "empty value (--no-proxy '') disables proxying entirely, ignoring "
            "any proxy environment variables. Ignored on a run that loads a "
            "config file, whether via --config or a ./vip.toml (use a [proxy] "
            "section there instead)."
        ),
    )

    # Config file
    verify_parser.add_argument(
        "--config",
        default=None,
        help="Path to vip.toml (default: VIP_CONFIG env var or ./vip.toml)",
    )

    # Auth
    auth_group = verify_parser.add_argument_group("authentication")
    auth_group.add_argument(
        "--idp",
        default=None,
        help='Identity provider for --headless-auth: "keycloak", "okta", "snowflake". '
        'Presence implies provider = "oidc" unless overridden by --provider or vip.toml.',
    )
    auth_group.add_argument(
        "--provider",
        default=None,
        help=f"Auth provider for --headless-auth/--interactive-auth: "
        f"{', '.join(_IDP_PROVIDERS)}. Overrides both --idp's implied "
        f'"oidc" and any provider inherited from vip.toml.',
    )
    verify_parser.add_argument(
        "--interactive-auth",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Launch a browser for OIDC login (default: disabled, use "
        "--interactive-auth to enable)",
    )
    verify_parser.add_argument(
        "--headless-auth",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Automate login in a headless browser (OIDC/SAML/OAuth2 requires "
            "[auth] idp). If VIP_TEST_TOTP_SECRET is set (a base32 TOTP seed "
            "for a TEST SERVICE ACCOUNT), VIP auto-fills the MFA code instead "
            "of prompting. Never use a personal account's seed."
        ),
    )
    verify_parser.add_argument(
        "--no-auth",
        action="store_true",
        default=False,
        help="Skip all tests that require authentication (Connect and Workbench)",
    )
    verify_parser.add_argument(
        "--api-auth",
        action="store_true",
        default=False,
        help="Run only API-key-authenticated tests; skip tests requiring browser credentials",
    )

    # Test selection
    verify_parser.add_argument(
        "--categories",
        default=None,
        help="Test categories as a pytest marker expression "
        "(e.g. 'connect', 'package-manager', 'workbench'). "
        "To include performance tests use --performance-tests instead.",
    )
    verify_parser.add_argument(
        "--performance-tests",
        action="store_true",
        default=False,
        help="Include performance tests in the default selection (excluded otherwise). "
        "Has no effect when --categories is also specified.",
    )
    verify_parser.add_argument(
        "--basic",
        action="store_true",
        default=False,
        help="Run only the basic subset; exclude detailed/long-running checks "
        "tagged @slow (IDE extensions, jobs, git ops, publish to Connect). "
        "Composes with --categories.",
    )
    verify_parser.add_argument(
        "-f",
        "--filter",
        default=None,
        dest="filter_expr",
        help="Filter tests by name expression, passed to pytest -k "
        "(e.g. 'test_login', 'test_login and not saml')",
    )
    verify_parser.add_argument(
        "--report",
        default="report/results.json",
        help="Write JSON results to this path for Quarto report generation"
        " (default: report/results.json)",
    )
    verify_parser.add_argument(
        "--format",
        default="json",
        help="Comma-separated output formats: json,junit,sarif. json (results.json)"
        " is always written; junit/sarif land beside --report. (default: json)",
    )
    verify_parser.add_argument(
        "--ci",
        action="store_true",
        default=False,
        help="CI preset: emit json,junit,sarif and use concise tracebacks (--tb=short)."
        " Overrides --format. Not compatible with --interactive-auth/--headless-auth.",
    )
    verify_parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Show full pytest tracebacks instead of concise error messages",
    )
    verify_parser.add_argument(
        "--extensions",
        action="append",
        default=[],
        help="Additional directories containing custom test cases (repeatable)",
    )
    verify_parser.add_argument(
        "--test-timeout",
        type=int,
        default=DEFAULT_TEST_TIMEOUT_SECONDS,
        help=(
            "Timeout in seconds for the pytest subprocess "
            f"(default: {DEFAULT_TEST_TIMEOUT_SECONDS}). "
            "A full Connect run includes content deployments that each take "
            "several minutes (R package restore, Python venv creation), so "
            "raise this further for large suites or slow servers. For "
            "per-deploy limits, set deploy_timeout under [connect] in vip.toml."
        ),
    )

    verify_parser.add_argument(
        "--allow-unproven",
        action="store_true",
        default=False,
        help=(
            "Exit 0 even when checks could not be verified. By default a check "
            "that VIP was asked to run but could not (for example, a configured "
            "product whose authentication never completed) fails the run, so an "
            "unverified deployment is not reported as a passing one."
        ),
    )

    # Pytest passthrough
    verify_parser.add_argument(
        "pytest_args",
        nargs="*",
        default=[],
        help="Additional arguments passed to pytest (place after --)",
    )
    verify_parser.set_defaults(func=run_verify)

    # vip cleanup
    cleanup_parser = subparsers.add_parser(
        "cleanup",
        help="Delete VIP _vip_test content from Connect and quit orphaned Workbench sessions",
        description=(
            "Delete VIP _vip_test-tagged content from Connect, and/or quit orphaned\n"
            "VIP-named Workbench sessions. At least one of --connect-url /\n"
            "--workbench-url (or the corresponding vip.toml URL) must resolve.\n\n"
            "  vip cleanup --connect-url https://connect.example.com\n"
            "  vip cleanup --workbench-url https://workbench.example.com\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cleanup_parser.add_argument(
        "--connect-url",
        default=None,
        help="Connect server URL (falls back to vip.toml if omitted)",
    )
    cleanup_parser.add_argument(
        "--api-key",
        default=None,
        help="Connect API key (default: VIP_CONNECT_API_KEY env var)",
    )
    cleanup_parser.add_argument(
        "--workbench-url",
        default=None,
        help=(
            "Workbench server URL (falls back to vip.toml if omitted). Quits orphaned "
            "VIP-named sessions via the session API, escalating to a browser-driven UI "
            "sweep if the API is unreachable or sessions persist. Requires "
            "VIP_TEST_USERNAME/VIP_TEST_PASSWORD for non-interactive auth, or an "
            "interactive browser login."
        ),
    )
    cleanup_tls_group = cleanup_parser.add_argument_group("TLS configuration")
    cleanup_tls_group.add_argument(
        "--insecure",
        action="store_true",
        default=False,
        help=(
            "Disable TLS certificate verification (equivalent to curl -k). "
            "Use only in trusted environments; this silently ignores certificate errors. "
            "For Playwright browser contexts, this sets ignore_https_errors=True. "
            "Note: --ca-bundle is preferred when you have a custom CA certificate."
        ),
    )
    cleanup_tls_group.add_argument(
        "--ca-bundle",
        default=None,
        metavar="PATH",
        type=Path,
        help=(
            "Path to a custom CA certificate bundle (PEM) to trust. "
            "Useful for self-signed or corporate CAs. "
            "For Playwright, sets NODE_EXTRA_CA_CERTS before launching Chromium "
            "(Chromium-level trust only; does not update the OS certificate store)."
        ),
    )
    cleanup_parser.set_defaults(func=run_cleanup)

    # vip install
    install_parser = subparsers.add_parser(
        "install",
        help="Install system packages and Playwright Chromium",
        description=(
            "Install VIP's machine-side dependencies: Chromium runtime libraries "
            "(via dnf or apt) and Playwright's Chromium browser. "
            "Records what was installed in .vip-install.json so vip uninstall can "
            "reverse only what this command added."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    install_parser.add_argument(
        "--skip-system",
        action="store_true",
        default=False,
        help=(
            "Skip the system-package step. VIP will not record those packages in "
            ".vip-install.json, so vip uninstall will not propose removing them. "
            "Use this when you manage system packages yourself or don't have sudo."
        ),
    )
    install_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print the plan without executing.",
    )
    install_parser.set_defaults(func=run_install)

    # vip uninstall
    uninstall_parser = subparsers.add_parser(
        "uninstall",
        help="Reverse vip install (dry-run by default; --yes to execute)",
        description=(
            "Reverse vip install using the per-project .vip-install.json manifest. "
            "Removes the Playwright cache and manifest; prints the sudo command for "
            "any system packages vip recorded so you can remove them yourself. "
            "Always prints a dry-run plan; pass --yes to execute the user-space steps."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    uninstall_parser.add_argument("--yes", action="store_true", default=False)
    uninstall_parser.add_argument("--force-host", action="store_true", default=False)
    uninstall_parser.add_argument(
        "--connect-url",
        default=None,
        help="Connect URL for chained vip cleanup (default: config / autodetect).",
    )
    uninstall_parser.add_argument("--api-key", default=None)
    # uninstall's chained cleanup only ever constructs a ConnectClient (no
    # Playwright/browser path, unlike verify and cleanup's Workbench sweep),
    # so its help text drops the Playwright-specific sentences verify's
    # otherwise-identical help carries -- they'd promise an effect uninstall
    # cannot produce.
    uninstall_tls_group = uninstall_parser.add_argument_group("TLS configuration")
    uninstall_tls_group.add_argument(
        "--insecure",
        action="store_true",
        default=False,
        help=(
            "Disable TLS certificate verification (equivalent to curl -k). "
            "Use only in trusted environments; this silently ignores certificate errors. "
            "Note: --ca-bundle is preferred when you have a custom CA certificate."
        ),
    )
    uninstall_tls_group.add_argument(
        "--ca-bundle",
        default=None,
        metavar="PATH",
        type=Path,
        help=(
            "Path to a custom CA certificate bundle (PEM) to trust. "
            "Useful for self-signed or corporate CAs."
        ),
    )
    uninstall_parser.set_defaults(func=run_uninstall)

    # vip report
    report_parser = subparsers.add_parser(
        "report",
        help="Render the Quarto report from a results.json file",
    )
    report_parser.add_argument(
        "--results",
        default="report/results.json",
        help="Path to results.json (default: report/results.json)",
    )
    report_parser.add_argument(
        "--open",
        action="store_true",
        default=False,
        help="Open the rendered report in a browser after rendering",
    )
    report_parser.set_defaults(func=run_report)

    # vip status
    status_parser = subparsers.add_parser(
        "status",
        help="Check health endpoints for each configured product",
    )
    status_parser.add_argument(
        "--config",
        default=None,
        help="Path to vip.toml (default: VIP_CONFIG env var or ./vip.toml)",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit machine-readable JSON instead of human-formatted text",
    )
    status_parser.set_defaults(func=run_status)

    # vip scaffold
    scaffold_parser = subparsers.add_parser(
        "scaffold",
        help="Generate a ready-to-run custom test extension directory",
        description=(
            "Copy a scaffold template to a new directory, ready to customise and run\n"
            "with:\n\n"
            "  vip verify --config vip.toml --extensions <output-dir>\n\n"
            "Templates range from a minimal single-scenario health check to a fuller\n"
            "cross-product example spanning Workbench and Connect. Run\n"
            "'vip scaffold --list' to see what's available. Every template also\n"
            "receives an AGENTS.md documenting VIP's fixtures, markers, and client\n"
            "layers for anyone (human or AI assistant) writing the extension."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    scaffold_parser.add_argument(
        "--output",
        default="./custom_tests",
        metavar="DIR",
        help="Destination directory for the scaffolded extension (default: ./custom_tests)",
    )
    scaffold_parser.add_argument(
        "--template",
        default=_DEFAULT_SCAFFOLD_TEMPLATE,
        metavar="NAME",
        help=(
            "Which template to scaffold (default: %(default)s). "
            "Run 'vip scaffold --list' for the available templates."
        ),
    )
    scaffold_parser.add_argument(
        "--list",
        action="store_true",
        default=False,
        help="List available templates and exit",
    )
    scaffold_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite destination if it already exists",
    )
    scaffold_parser.set_defaults(func=run_scaffold)

    # Map command names to their parsers for context-appropriate help
    subcommand_parsers = {
        "version": version_parser,
        "verify": verify_parser,
        "cleanup": cleanup_parser,
        "install": install_parser,
        "uninstall": uninstall_parser,
        "auth": auth_parser,
        "report": report_parser,
        "status": status_parser,
        "scaffold": scaffold_parser,
    }

    argv = _reorder_help_args(sys.argv[1:], set(subcommand_parsers))
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        sub = subcommand_parsers.get(args.command)
        if sub:
            sub.print_help()
        else:
            parser.print_help()
        sys.exit(1)
    try:
        args.func(args)
    except VipError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(exc.exit_code)
