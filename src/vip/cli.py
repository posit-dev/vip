"""VIP command-line tools for credential management and verification."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vip.config import Mode

# Buffer subtracted from the user-supplied timeout when setting the pytest
# timeout inside the K8s Job.  The Job's own deadline is set to args.timeout,
# so we give pytest a slightly shorter limit so it can finish and write results
# before Kubernetes kills the pod.
_JOB_CLEANUP_BUFFER_SECONDS = 60
_JOB_MIN_PYTEST_TIMEOUT_SECONDS = 60

# Valid test categories. Maps every accepted spelling (hyphenated and
# underscored) to the internal pytest marker name.
VALID_CATEGORIES: dict[str, str] = {
    "prerequisites": "prerequisites",
    "connect": "connect",
    "workbench": "workbench",
    "package-manager": "package_manager",
    "package_manager": "package_manager",
    "cross-product": "cross_product",
    "cross_product": "cross_product",
    "performance": "performance",
    "security": "security",
}

# Marker expression keywords that are not category names.
_MARKER_KEYWORDS = {"and", "or", "not"}

# Regex matching a complete identifier token (may contain hyphens or
# underscores).  Negative lookbehind/lookahead ensure we don't match a
# substring inside a larger token like ``_connect`` or ``1connect``.
_IDENT_RE = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z][A-Za-z0-9_-]*(?![A-Za-z0-9_-])")


def _valid_categories_message() -> str:
    """Return a comma-separated string of preferred (hyphenated) category names."""
    seen: dict[str, str] = {}
    for k, v in VALID_CATEGORIES.items():
        if v not in seen or "-" in k:
            seen[v] = k
    return ", ".join(sorted(seen.values()))


def _normalize_categories(expr: str) -> str:
    """Validate and normalize a ``--categories`` expression.

    Accepts user-facing hyphenated names (e.g. ``package-manager``) as well
    as underscore names (``package_manager``) and translates both to the
    internal pytest marker names.  Raises :class:`SystemExit` if any
    identifier token is not a recognised category or keyword.
    """

    def _replace(match: re.Match[str]) -> str:
        word = match.group(0)
        if word in _MARKER_KEYWORDS:
            return word
        if word in VALID_CATEGORIES:
            return VALID_CATEGORIES[word]
        print(
            f"Error: unknown category '{word}'. Valid categories: {_valid_categories_message()}",
            file=sys.stderr,
        )
        sys.exit(1)

    result = _IDENT_RE.sub(_replace, expr)
    # After substitution, only whitespace and parentheses should remain
    # between identifiers.  Any leftover characters (digits, underscores
    # from malformed tokens like ``_connect`` or ``1connect``) are invalid.
    leftover = _IDENT_RE.sub("", result).replace("(", "").replace(")", "").strip()
    if leftover:
        print(
            f"Error: invalid characters in category expression: '{expr}'. "
            f"Valid categories: {_valid_categories_message()}",
            file=sys.stderr,
        )
        sys.exit(1)
    return result


def _connect_cluster(cluster_config) -> Path:
    """Generate kubeconfig and set KUBECONFIG env var. Returns the path."""
    from vip.cluster.target import validate_cluster_config

    validate_cluster_config(cluster_config)

    if cluster_config.provider == "aws":
        from vip.cluster.aws import get_eks_kubeconfig

        kubeconfig_path = get_eks_kubeconfig(
            cluster_config.name,
            cluster_config.region,
            cluster_config.profile or None,
            cluster_config.role_arn or None,
        )
    elif cluster_config.provider == "azure":
        from vip.cluster.azure import get_aks_kubeconfig

        kubeconfig_path = get_aks_kubeconfig(
            cluster_config.name,
            cluster_config.resource_group,
            cluster_config.subscription_id,
        )
    else:
        raise ValueError(f"Unknown provider: {cluster_config.provider!r}")

    os.environ["KUBECONFIG"] = str(kubeconfig_path)
    print(f"Connected to cluster: {cluster_config.name}", file=sys.stderr)
    return kubeconfig_path


def mint_connect_key(args: argparse.Namespace) -> None:
    """Launch interactive browser auth and mint a Connect API key."""
    from vip.auth import start_interactive_auth

    session = start_interactive_auth(args.url)

    if not session.api_key:
        print(json.dumps({"error": "Failed to mint API key"}), file=sys.stderr)
        sys.exit(1)

    result = {
        "api_key": session.api_key,
        "key_name": session.key_name,
    }

    print(json.dumps(result))


def connect_to_cluster(args: argparse.Namespace) -> None:
    """Generate kubeconfig for a cluster and print the path."""
    from vip.config import load_config

    config = load_config()

    if args.provider:
        config.cluster.provider = args.provider
    if args.cluster_name:
        config.cluster.name = args.cluster_name
    if args.region:
        config.cluster.region = args.region
    if args.resource_group:
        config.cluster.resource_group = args.resource_group
    if args.subscription_id:
        config.cluster.subscription_id = args.subscription_id
    if args.profile:
        config.cluster.profile = args.profile

    kubeconfig_path = _connect_cluster(config.cluster)
    print(str(kubeconfig_path))


# ---------------------------------------------------------------------------
# Config generation from CLI URL args
# ---------------------------------------------------------------------------


def _print_skip_notes(config_path: str | None) -> None:
    """Print a note for each product that is not configured."""
    from vip.config import load_config

    cfg = load_config(config_path)
    products = [
        ("Connect", cfg.connect),
        ("Workbench", cfg.workbench),
        ("Package Manager", cfg.package_manager),
    ]
    for name, pc in products:
        if not pc.is_configured:
            if not pc.enabled:
                reason = "disabled"
            else:
                reason = "no URL given"
            print(f"Note: {name} {reason} — {name} tests will not be collected.", flush=True)


def _print_credential_warnings(config_path: str | None, *, interactive_auth: bool) -> None:
    """Warn when products are configured but credentials are missing."""
    from vip.config import load_config

    cfg = load_config(config_path)
    if interactive_auth:
        return

    has_username = bool(cfg.auth.username)
    needs_creds: list[str] = []

    if cfg.connect.is_configured and not cfg.connect.api_key and not has_username:
        needs_creds.append("Connect")
    if cfg.workbench.is_configured and not has_username:
        needs_creds.append("Workbench")

    if needs_creds:
        products = " and ".join(needs_creds)
        print(
            f"Warning: {products} tests selected but no credentials provided. "
            "Set VIP_TEST_USERNAME and VIP_TEST_PASSWORD, or use --interactive-auth.",
            flush=True,
        )


# Pytest options that consume the next argument as a directory path.
# We skip these values so they aren't mistaken for positional test targets.
_CONSUMES_DIR_VALUE = frozenset({"--rootdir", "--confcutdir", "--basetemp"})


def _has_explicit_test_targets(pytest_args: list[str]) -> bool:
    """Return True if *pytest_args* contains what looks like test paths or nodeids.

    This avoids injecting the default ``vip_tests`` path when the user already
    passed explicit targets after ``--`` (e.g. ``vip verify -- tests/foo.py``).
    Directory values consumed by known pytest options (``--rootdir``, etc.) are
    excluded so they don't trigger false-positive detection.
    """
    skip_next = False
    for arg in pytest_args:
        if skip_next:
            skip_next = False
            continue
        if arg in _CONSUMES_DIR_VALUE:
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        if "::" in arg or arg.endswith(".py") or Path(arg).is_dir():
            return True
    return False


def _generate_temp_config(args: argparse.Namespace) -> str:
    """Write a minimal vip.toml from CLI URL arguments. Returns temp file path."""
    lines = ["[general]", 'deployment_name = "Posit Team"', ""]

    if args.connect_url:
        lines.extend(["[connect]", f'url = "{args.connect_url}"', ""])
    else:
        lines.extend(["[connect]", "enabled = false", ""])

    if args.workbench_url:
        lines.extend(["[workbench]", f'url = "{args.workbench_url}"', ""])
    else:
        lines.extend(["[workbench]", "enabled = false", ""])

    if args.package_manager_url:
        lines.extend(["[package_manager]", f'url = "{args.package_manager_url}"', ""])
    else:
        lines.extend(["[package_manager]", "enabled = false", ""])

    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write("\n".join(lines) + "\n")
        return f.name


# ---------------------------------------------------------------------------
# vip verify (combined local + K8s)
# ---------------------------------------------------------------------------


def _resolve_mode(args: argparse.Namespace) -> Mode:
    """Convert boolean CLI flags to a Mode enum value."""
    from vip.config import Mode

    if args.config_only:
        return Mode.config_only
    return Mode.k8s_job


def _phase_generate_config(args: argparse.Namespace) -> tuple[str, dict]:
    """Fetch PTD Site CR and return (vip_config_toml, site_cr) tuple."""
    from vip.verify.site import fetch_site_cr, generate_vip_config

    site = getattr(args, "site", "main")
    namespace = getattr(args, "namespace", "posit-team")
    name = getattr(args, "name", None) or "Posit Team"

    print(f"Fetching PTD Site CR: {site} (namespace: {namespace})")
    site_cr = fetch_site_cr(site, namespace)
    return generate_vip_config(site_cr, name), site_cr


def _phase_provision_credentials(site_cr: dict, args: argparse.Namespace) -> None:
    """Provision test credentials in the K8s cluster."""
    from vip.verify.site import _extract_connect_url, _extract_keycloak_url

    if args.interactive_auth:
        from vip.verify.credentials import mint_interactive_credentials

        connect_url = _extract_connect_url(site_cr)
        if not connect_url:
            print("Error: Connect URL not found in PTD Site CR", file=sys.stderr)
            sys.exit(1)
        site = getattr(args, "site", "main")
        namespace = getattr(args, "namespace", "posit-team")
        print("Minting credentials via interactive auth...")
        mint_interactive_credentials(connect_url, site, namespace)
    else:
        keycloak_url = _extract_keycloak_url(site_cr)
        if keycloak_url:
            from vip.verify.credentials import ensure_keycloak_test_user

            site = getattr(args, "site", "main")
            namespace = getattr(args, "namespace", "posit-team")
            admin_secret_name = f"{site}-keycloak-initial-admin"
            print(f"Ensuring Keycloak test user exists (admin secret: {admin_secret_name})")
            try:
                ensure_keycloak_test_user(
                    keycloak_url,
                    "posit",
                    "vip-test-user",
                    admin_secret_name,
                    namespace,
                )
            except Exception as e:
                print(
                    f"Warning: Could not create Keycloak test user: {e}",
                    file=sys.stderr,
                )
                print("Continuing without Keycloak credentials...", file=sys.stderr)


def run_verify(args: argparse.Namespace) -> None:
    """Run VIP tests. Handles both local and K8s modes."""
    if args.k8s or args.config_only:
        _run_verify_k8s(args)
        return

    _run_verify_local(args)


def _run_verify_local(args: argparse.Namespace) -> None:
    """Run VIP tests locally against URL args or a vip.toml config."""
    config_path = args.config
    temp_config = None

    if not config_path and (args.connect_url or args.workbench_url or args.package_manager_url):
        temp_config = _generate_temp_config(args)
        config_path = temp_config

    # Fail fast when a config file is expected but doesn't exist.
    if config_path and not Path(config_path).is_file():
        print(f"Error: config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    if not config_path:
        # No explicit config and no URL args — check the default resolution.
        env = os.environ.get("VIP_CONFIG")
        default = Path(env) if env else Path("vip.toml")
        if not default.is_file():
            print(f"Error: config file not found: {default}", file=sys.stderr)
            print(
                "Provide a config file with --config, or pass product URLs directly "
                "(e.g. --connect-url https://connect.example.com).",
                file=sys.stderr,
            )
            sys.exit(1)

    # Print notes for products that are not configured so the user knows
    # upfront which categories will be skipped.
    _print_skip_notes(config_path)
    _print_credential_warnings(config_path, interactive_auth=args.interactive_auth)

    cmd = [sys.executable, "-m", "pytest", "-v"]

    # Resolve the installed vip_tests package so pytest finds tests even
    # when running outside the source tree (e.g. ``pip install posit-vip``).
    # Skip when the user already passed explicit test targets after ``--``.
    if not _has_explicit_test_targets(args.pytest_args):
        from importlib.util import find_spec

        _spec = find_spec("vip_tests")
        if _spec and _spec.submodule_search_locations:
            cmd.append(_spec.submodule_search_locations[0])

    if config_path:
        cmd.append(f"--vip-config={config_path}")
    if args.report:
        cmd.append(f"--vip-report={args.report}")
    if args.interactive_auth:
        cmd.append("--interactive-auth")
    for ext in args.extensions or []:
        cmd.append(f"--vip-extensions={ext}")
    if args.categories:
        cmd.extend(["-m", _normalize_categories(args.categories)])
    if args.filter_expr:
        cmd.extend(["-k", args.filter_expr])

    if args.verbose:
        cmd.append("--vip-verbose")
    cmd.extend(args.pytest_args)

    try:
        result = subprocess.run(cmd)
        sys.exit(result.returncode)
    finally:
        if temp_config:
            Path(temp_config).unlink(missing_ok=True)


def _run_verify_k8s(args: argparse.Namespace) -> None:
    """K8s workflow: fetch PTD Site CR, provision credentials, run as Job."""
    from vip.config import Mode, load_config

    config = load_config()
    mode = _resolve_mode(args)
    config.validate_for_mode(mode)

    if config.cluster.is_configured:
        _connect_cluster(config.cluster)

    vip_config_toml, site_cr = _phase_generate_config(args)

    if mode == Mode.config_only:
        print(vip_config_toml)
        return

    _phase_provision_credentials(site_cr, args)
    _run_k8s_job(vip_config_toml, args)


def _run_k8s_job(vip_config_toml: str, args: argparse.Namespace) -> None:
    """Run VIP tests as a K8s Job."""
    from vip.verify.job import cleanup, create_config_map, create_job, stream_logs, wait_for_job

    namespace = getattr(args, "namespace", "posit-team")
    suffix = secrets.token_hex(4)
    job_name = f"vip-verify-{suffix}"
    cm_name = f"vip-config-{suffix}"

    try:
        print(f"Creating ConfigMap: {cm_name}")
        create_config_map(cm_name, namespace, vip_config_toml)

        print(f"Creating Job: {job_name}")
        pytest_timeout = args.timeout - _JOB_CLEANUP_BUFFER_SECONDS
        if pytest_timeout <= 0:
            import warnings

            warnings.warn(
                f"--timeout ({args.timeout}s) is too short to subtract the "
                f"{_JOB_CLEANUP_BUFFER_SECONDS}s cleanup buffer. "
                f"Using minimum pytest timeout of {_JOB_MIN_PYTEST_TIMEOUT_SECONDS}s.",
                stacklevel=2,
            )
            pytest_timeout = _JOB_MIN_PYTEST_TIMEOUT_SECONDS
        create_job(
            job_name,
            namespace,
            cm_name,
            image=args.image,
            categories=_normalize_categories(args.categories) if args.categories else None,
            filter_expr=getattr(args, "filter_expr", None),
            timeout_seconds=pytest_timeout,
            verbose=getattr(args, "verbose", False),
        )

        print(f"Streaming logs from Job: {job_name}")
        stream_logs(job_name, namespace, timeout=args.timeout)

        print(f"Waiting for Job to complete: {job_name}")
        success = wait_for_job(job_name, namespace, timeout=args.timeout)

        if not success:
            print("Verification failed", file=sys.stderr)
            sys.exit(1)
        else:
            print("Verification completed successfully")
    finally:
        print(f"Cleaning up Job and ConfigMap: {job_name}, {cm_name}")
        cleanup(job_name, cm_name, namespace)


def run_report(args: argparse.Namespace) -> None:
    """Render the Quarto report from a results.json file."""
    import shutil
    import webbrowser

    results_src = Path(args.results)
    results_dest = Path("report/results.json")

    if results_src.resolve() != results_dest.resolve():
        if not results_src.exists():
            print(f"Error: results file not found: {results_src}", file=sys.stderr)
            sys.exit(1)
        shutil.copy2(results_src, results_dest)

    result = subprocess.run(["quarto", "render"], cwd="report")

    if args.open and result.returncode == 0:
        webbrowser.open(str(Path("report/_site/index.html").resolve()))

    sys.exit(result.returncode)


def run_status(args: argparse.Namespace) -> None:
    """Run preflight health checks against each configured product."""
    from vip.clients.packagemanager import PackageManagerClient
    from vip.clients.workbench import WorkbenchClient
    from vip.config import load_config

    config = load_config(args.config)

    checks = [
        ("connect", config.connect),
        ("workbench", config.workbench),
        ("package_manager", config.package_manager),
    ]

    results = []
    for name, pc in checks:
        if not pc.is_configured:
            results.append((name, "not configured", "skip"))
            continue
        try:
            if name == "connect":
                from vip.clients.connect import ConnectClient as CC

                client: CC | WorkbenchClient | PackageManagerClient = CC(
                    pc.url,
                    pc.api_key,  # type: ignore[attr-defined]
                )
            elif name == "workbench":
                client = WorkbenchClient(pc.url, pc.api_key)  # type: ignore[attr-defined]
            else:
                client = PackageManagerClient(pc.url, pc.token)  # type: ignore[attr-defined]
            status = client.health()
            state = "ok" if status < 400 else "fail"
            results.append((name, f"HTTP {status}", state))
        except Exception as e:
            results.append((name, str(e), "fail"))

    for name, detail, state in results:
        print(f"  {state.upper():4s}  {name:20s}  {detail}")

    sys.exit(0 if all(s in ("ok", "skip") for _, _, s in results) else 1)


def run_app(args: argparse.Namespace) -> None:
    """Launch the VIP Shiny app."""
    try:
        from shiny import run_app as _run_shiny  # noqa: F811
    except ImportError:
        print(
            "Error: the 'shiny' package is not installed.\nInstall with: uv sync",
            file=sys.stderr,
        )
        sys.exit(1)

    # The --config flag is not currently supported for the Shiny app.
    # Fail fast instead of silently ignoring it.
    if getattr(args, "config", None):
        print(
            "Error: the '--config' option is not supported for 'vip app' at this time.",
            file=sys.stderr,
        )
        sys.exit(2)

    _run_shiny(  # type: ignore[misc]  # shiny is an optional dep
        "vip.app.app:app",
        host=args.host,
        port=args.port,
        launch_browser=not args.no_browser,
    )


def run_cleanup(args: argparse.Namespace) -> None:
    """Delete VIP test credentials and resources.

    Supports two modes:

    - **Local mode** (auto-detected or ``--connect-url``): connects directly
      to a Connect server and deletes all content tagged ``_vip_test``.
    - **Cluster mode**: uses the PTD Site CR to look up credentials and runs
      the full cluster-aware cleanup (K8s secrets, etc.).

    Local mode is used when *any* of the following is true:
    - ``--connect-url`` is provided on the command line, or
    - no cluster config is present in ``vip.toml`` and a Connect URL is found
      in the config file.
    """
    from vip.config import load_config

    config = load_config()

    # Determine Connect URL and API key for local content cleanup.
    connect_url = getattr(args, "connect_url", None)
    api_key = getattr(args, "api_key", None) or os.environ.get("VIP_CONNECT_API_KEY", "")

    # Auto-detect local mode: explicit --connect-url or no cluster config.
    use_local = bool(connect_url) or not config.cluster.is_configured

    if use_local:
        # Fall back to config file values when no CLI override is supplied.
        if not connect_url and config.connect and config.connect.url:
            connect_url = config.connect.url
        if not connect_url:
            print(
                "Error: no Connect URL found. Pass --connect-url or set [connect] url in vip.toml.",
                file=sys.stderr,
            )
            sys.exit(1)

        from vip.clients.connect import ConnectClient

        print(f"Cleaning up VIP test content on Connect at {connect_url}")
        with ConnectClient(connect_url, api_key) as client:
            deleted = client.cleanup_vip_content()
        print(f"Deleted {deleted} VIP test content item(s)")
        print("Cleanup completed successfully")
        return

    # Cluster mode: requires K8s access.
    from vip.verify.credentials import cleanup_credentials
    from vip.verify.site import _extract_connect_url, fetch_site_cr

    if config.cluster.is_configured:
        _connect_cluster(config.cluster)

    site_cr = fetch_site_cr(args.site, args.namespace)
    connect_url = _extract_connect_url(site_cr)

    print(f"Cleaning up credentials for site: {args.site}")
    cleanup_credentials(args.namespace, connect_url)
    print("Cleanup completed successfully")


def main() -> None:
    """Main entry point for the VIP CLI."""
    parser = argparse.ArgumentParser(
        prog="vip", description="VIP verification and credential tools"
    )
    subparsers = parser.add_subparsers(dest="command")

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
            "Kubernetes mode (requires posit-dev/team-operator PTD Site CR):\n"
            "  vip verify --k8s --site main --namespace posit-team\n\n"
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

    # Config file
    verify_parser.add_argument(
        "--config",
        default=None,
        help="Path to vip.toml (default: VIP_CONFIG env var or ./vip.toml)",
    )

    # Auth
    verify_parser.add_argument(
        "--interactive-auth",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Launch a browser for OIDC login (default: disabled, use "
        "--interactive-auth to enable)",
    )

    # Test selection
    verify_parser.add_argument(
        "--categories",
        default=None,
        help="Test categories as a pytest marker expression "
        "(e.g. 'connect', 'package-manager', 'performance and workbench')",
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

    # K8s mode
    k8s_group = verify_parser.add_argument_group("Kubernetes mode")
    k8s_group.add_argument(
        "--k8s",
        action="store_true",
        default=False,
        help="Fetch config from a PTD Site CR and run tests as a K8s Job "
        "(requires posit-dev/team-operator)",
    )
    k8s_group.add_argument("--site", default="main", help="PTD Site CR name (default: main)")
    k8s_group.add_argument(
        "--namespace",
        default="posit-team",
        help="Kubernetes namespace (default: posit-team)",
    )
    k8s_group.add_argument(
        "--name",
        default=None,
        help="Deployment name for reports (default: Posit Team)",
    )
    k8s_group.add_argument(
        "--image",
        default="ghcr.io/posit-dev/vip:latest",
        help="VIP container image (default: ghcr.io/posit-dev/vip:latest)",
    )
    k8s_group.add_argument(
        "--timeout",
        type=int,
        default=900,
        help="Job timeout in seconds (default: 900)",
    )
    k8s_group.add_argument(
        "--config-only",
        action="store_true",
        default=False,
        help="Generate config from PTD Site CR and print it (no tests run)",
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
        help="Delete VIP test credentials and resources",
        description=(
            "Delete VIP test credentials and resources.\n\n"
            "Local mode (auto-detected when no cluster config is present):\n"
            "  vip cleanup --connect-url https://connect.example.com\n\n"
            "Cluster mode (requires K8s access and PTD Site CR):\n"
            "  vip cleanup --site main --namespace posit-team\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    local_group = cleanup_parser.add_argument_group(
        "local mode (Connect content cleanup, no K8s required)"
    )
    local_group.add_argument(
        "--connect-url",
        default=None,
        help="Connect server URL (enables local mode; falls back to vip.toml if omitted)",
    )
    local_group.add_argument(
        "--api-key",
        default=None,
        help="Connect API key (default: VIP_CONNECT_API_KEY env var)",
    )
    cluster_group = cleanup_parser.add_argument_group("cluster mode (K8s credential cleanup)")
    cluster_group.add_argument("--site", default="main", help="PTD Site CR name (default: main)")
    cluster_group.add_argument(
        "--namespace",
        default="posit-team",
        help="Kubernetes namespace (default: posit-team)",
    )
    cleanup_parser.set_defaults(func=run_cleanup)

    # vip cluster
    cluster_parser = subparsers.add_parser("cluster", help="Cluster connection tools")
    cluster_sub = cluster_parser.add_subparsers(dest="cluster_command")

    # vip cluster connect
    connect_parser = cluster_sub.add_parser("connect", help="Generate kubeconfig for a cluster")
    connect_parser.add_argument("--provider", help="Cloud provider (aws or azure)")
    connect_parser.add_argument("--cluster-name", help="Cluster name")
    connect_parser.add_argument("--region", help="Cloud region (AWS)")
    connect_parser.add_argument("--resource-group", help="Resource group (Azure)")
    connect_parser.add_argument("--subscription-id", help="Subscription ID (Azure)")
    connect_parser.add_argument("--profile", help="AWS profile name")
    connect_parser.set_defaults(func=connect_to_cluster)

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
    status_parser.set_defaults(func=run_status)

    # vip app
    app_parser = subparsers.add_parser(
        "app",
        help="Launch the VIP Shiny app (graphical test runner)",
    )
    app_parser.add_argument(
        "--config",
        default=None,
        help="Path to vip.toml (passed to the app as default config)",
    )
    app_parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    app_parser.add_argument("--port", type=int, default=0, help="Port (default: auto)")
    app_parser.add_argument(
        "--no-browser",
        action="store_true",
        default=False,
        help="Don't open a browser window automatically",
    )
    app_parser.set_defaults(func=run_app)

    # Map command names to their parsers for context-appropriate help
    subcommand_parsers = {
        "verify": verify_parser,
        "cleanup": cleanup_parser,
        "auth": auth_parser,
        "cluster": cluster_parser,
        "report": report_parser,
        "status": status_parser,
        "app": app_parser,
    }

    args = parser.parse_args()
    if not hasattr(args, "func"):
        sub = subcommand_parsers.get(args.command)
        if sub:
            sub.print_help()
        else:
            parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
