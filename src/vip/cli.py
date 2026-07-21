"""VIP command-line tools for credential management and verification."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from vip.timeouts import scaled

if TYPE_CHECKING:
    from vip.config import VIPConfig

# Default for ``vip verify --test-timeout``.  Generous enough for a full
# Connect suite with several content deployments (each can take 3-5 minutes
# for R package restore or Python venv creation).
DEFAULT_TEST_TIMEOUT_SECONDS = int(scaled(3600))

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
    "config-hygiene": "config_hygiene",
    "config_hygiene": "config_hygiene",
}

# Categories that are excluded from the default ``vip verify`` run and only
# executed when the user explicitly opts in, either via ``--categories`` or
# a dedicated opt-in flag (for example ``--performance-tests``). These tests
# check VIP's own configuration rather than the Posit deployment.
_OPT_IN_CATEGORIES = frozenset({"config_hygiene", "performance"})

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


def _default_marker_expr(extra_keep: frozenset[str] = frozenset()) -> str:
    """Marker expression applied when the user doesn't pass ``--categories``.

    Excludes every opt-in category so that ``vip verify`` runs only the
    product-verification tests by default.  Pass ``extra_keep`` to re-include
    specific opt-in categories (e.g. ``frozenset({"performance"})`` when
    ``--performance-tests`` is set).
    """
    excluded = _OPT_IN_CATEGORIES - extra_keep
    return " and ".join(f"not {name}" for name in sorted(excluded))


def _extra_keep_from_args(args: argparse.Namespace) -> frozenset[str]:
    """Return the set of opt-in categories to re-include based on CLI flags.

    For example, ``--performance-tests`` adds ``"performance"`` to the set so
    that :func:`_default_marker_expr` keeps it in the expression.
    """
    extra: set[str] = set()
    if getattr(args, "performance_tests", False):
        extra.add("performance")
    return frozenset(extra)


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


# ---------------------------------------------------------------------------
# Config generation from CLI URL args
# ---------------------------------------------------------------------------


def _print_skip_notes(config_path: str | None) -> None:
    """Print a note for each product that is not configured."""
    from vip.config import load_config

    try:
        cfg = load_config(config_path)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
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


def _check_credentials(
    config_path: str | None,
    *,
    interactive_auth: bool,
    categories: str | None,
) -> None:
    """Exit early when products are configured but credentials are missing.

    When *categories* is provided, only check products whose marker appears
    in the expression.  Without categories all configured products are checked.
    """
    from vip.config import load_config

    try:
        cfg = load_config(config_path)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    if interactive_auth:
        return

    has_creds = bool(cfg.auth.username and cfg.auth.password)
    needs_creds: list[str] = []

    # When a category filter is active, only enforce credential checks for
    # products that are actually selected.  We tokenize the expression and
    # check that the marker appears as a positive term (not negated by "not").
    def _category_selected(marker: str) -> bool:
        if categories is None:
            return True
        tokens = re.findall(r"\w+", categories)
        for i, tok in enumerate(tokens):
            if tok == marker and (i == 0 or tokens[i - 1] != "not"):
                return True
        return False

    # Connect tests include UI login and user-management scenarios that use
    # VIP_TEST_USERNAME/VIP_TEST_PASSWORD even when VIP_CONNECT_API_KEY is set,
    # so require credentials whenever Connect is selected (users can pass
    # --no-auth to deselect Connect tests entirely).
    if cfg.connect.is_configured and not has_creds and _category_selected("connect"):
        needs_creds.append("Connect")
    if cfg.workbench.is_configured and not has_creds and _category_selected("workbench"):
        needs_creds.append("Workbench")

    if needs_creds:
        products = " and ".join(needs_creds)
        print(
            f"\033[1mError: {products} tests selected but no credentials provided.\033[0m\n"
            "Set VIP_TEST_USERNAME and VIP_TEST_PASSWORD (optionally with --headless-auth),\n"
            "or use --interactive-auth, or --no-auth to skip tests that require "
            "authentication.",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)


def _config_idp(config_path: str | None) -> str:
    """Return the normalized ``[auth] idp`` from the resolved config.

    This is the IdP the run will actually use: the ``--idp`` flag is folded
    into the generated config on URL-driven runs and is not otherwise forwarded
    to pytest, so the config file is the source of truth. Returns "" when there
    is no config or it can't be read (pytest surfaces config errors later).
    Normalized (stripped, lowercased) to match ``idp.get_idp_strategy``.
    """
    if not config_path:
        return ""
    from vip.config import load_config

    try:
        return (load_config(config_path).auth.idp or "").strip().lower()
    except ValueError:
        return ""


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


def _user_set_xdist(pytest_args: list[str]) -> tuple[bool, bool]:
    """Return (user_set_numprocesses, user_set_dist) from user-supplied pytest args.

    Lets `vip verify` supply default ``-n``/``--dist`` without overriding an
    explicit user choice (including ``-p no:xdist``, which disables xdist
    entirely and so counts as the user managing both).
    """
    set_n = False
    set_dist = False
    for a in pytest_args:
        if a in ("-n", "--numprocesses") or a.startswith(("-n", "--numprocesses=")):
            set_n = True
        if a.startswith("--dist") or a == "no:xdist" or a.startswith("no:xdist"):
            set_dist = True
    if "no:xdist" in pytest_args or any(x.startswith("no:xdist") for x in pytest_args):
        set_n = set_dist = True
    return set_n, set_dist


def _generate_temp_config(args: argparse.Namespace) -> str:
    """Write a minimal vip.toml from CLI URL arguments. Returns temp file path."""
    lines = ["[general]", 'deployment_name = "Posit Team"', ""]

    if args.connect_url:
        lines.extend(["[connect]", f"url = {json.dumps(args.connect_url)}"])
        connect_version = getattr(args, "connect_version", None)
        if connect_version:
            lines.append(f"version = {json.dumps(connect_version)}")
        lines.append("")
    else:
        lines.extend(["[connect]", "enabled = false", ""])

    if args.workbench_url:
        lines.extend(["[workbench]", f"url = {json.dumps(args.workbench_url)}"])
        workbench_version = getattr(args, "workbench_version", None)
        if workbench_version:
            lines.append(f"version = {json.dumps(workbench_version)}")
        lines.append("")
    else:
        lines.extend(["[workbench]", "enabled = false", ""])

    if args.package_manager_url:
        lines.extend(["[package_manager]", f"url = {json.dumps(args.package_manager_url)}"])
        package_manager_version = getattr(args, "package_manager_version", None)
        if package_manager_version:
            lines.append(f"version = {json.dumps(package_manager_version)}")
        lines.append("")
    else:
        lines.extend(["[package_manager]", "enabled = false", ""])

    idp = getattr(args, "idp", None)
    inherited_provider: str | None = None

    # Inherit from an existing vip.toml so ``vip verify --workbench-url ...
    # --headless-auth`` can pick up the [auth] section the user already
    # configured.  Done best-effort: a malformed vip.toml should not break a
    # URL-driven command that doesn't depend on it.
    env = os.environ.get("VIP_CONFIG")
    default_path = Path(env) if env else Path("vip.toml")
    if default_path.is_file():
        from vip.config import load_config

        try:
            existing = load_config(default_path)
        except Exception:
            existing = None
        if existing is not None:
            if not idp and existing.auth.idp:
                idp = existing.auth.idp
            if existing.auth.provider and existing.auth.provider != "password":
                inherited_provider = existing.auth.provider

    # Resolve the provider:
    # - With --idp set, the user wants IdP-based auth.  Keep an inherited
    #   IdP-class value (saml/oauth2) so specific declarations survive; but
    #   ignore inherited non-IdP providers (ldap) that would contradict the
    #   CLI intent — auth.py's flow selection keys off provider, not idp.
    # - Without --idp, just honour whatever vip.toml declared.
    _IDP_PROVIDERS = ("oidc", "saml", "oauth2")
    if idp:
        if inherited_provider in _IDP_PROVIDERS:
            auth_provider: str | None = inherited_provider
        else:
            auth_provider = "oidc"
    else:
        auth_provider = inherited_provider

    if auth_provider or idp:
        lines.append("[auth]")
        if auth_provider:
            lines.append(f'provider = "{auth_provider}"')
        if idp:
            lines.append(f'idp = "{idp}"')
        lines.append("")

    insecure = getattr(args, "insecure", False)
    ca_bundle = getattr(args, "ca_bundle", None)
    if insecure and ca_bundle:
        import warnings

        warnings.warn(
            "--insecure and --ca-bundle are both set; --insecure takes precedence "
            "and the ca-bundle path will be ignored for TLS verification.",
            stacklevel=2,
        )
    effective_ca_bundle = None if insecure else ca_bundle
    if insecure or effective_ca_bundle:
        lines.append("[tls]")
        if insecure:
            lines.append("insecure = true")
        if effective_ca_bundle:
            import json as _json

            lines.append(f"ca_bundle = {_json.dumps(str(effective_ca_bundle))}")
        lines.append("")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write("\n".join(lines) + "\n")
        return f.name


# ---------------------------------------------------------------------------
# vip verify
# ---------------------------------------------------------------------------


def run_verify(args: argparse.Namespace) -> None:
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
        # Pin the resolved default so pytest loads the same file the CLI
        # validated, regardless of pytest's rootdir or subprocess CWD.
        config_path = str(default.resolve())

    # Resolve explicit paths too so --vip-config always gets an absolute path.
    config_path = str(Path(config_path).resolve())

    if args.interactive_auth and args.headless_auth:
        print(
            "\033[1mError: --interactive-auth and --headless-auth are mutually exclusive.\033[0m",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)

    if args.no_auth and args.api_auth:
        print(
            "\033[1mError: --no-auth and --api-auth are mutually exclusive.\033[0m",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)

    if args.api_auth and _config_idp(config_path) == "snowflake":
        print(
            "\033[1mError: --api-auth is not supported with the Snowflake identity "
            "provider.\033[0m\n"
            "A Posit Team Native App authenticates through the Snowpark Container "
            "Services ingress and has no standalone product API key for --api-auth to "
            "use.\n"
            "Use --headless-auth to run the full suite, or --no-auth for the stateless "
            "checks that do not require a login.",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)

    # Print notes for products that are not configured so the user knows
    # upfront which categories will be skipped.
    _print_skip_notes(config_path)
    if not args.no_auth and not args.api_auth:
        _check_credentials(
            config_path,
            interactive_auth=args.interactive_auth or args.headless_auth,
            categories=args.categories,
        )

    cmd = [sys.executable, "-m", "pytest", "-v", "--no-header"]

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

    _VALID_FORMATS = {"json", "junit", "sarif"}
    fmt = "json,junit,sarif" if getattr(args, "ci", False) else getattr(args, "format", "json")
    requested = [f.strip().lower() for f in fmt.split(",") if f.strip()]
    unknown = [f for f in requested if f not in _VALID_FORMATS]
    if unknown:
        print(
            f"Error: unknown --format value(s): {', '.join(unknown)}. "
            f"Valid: {', '.join(sorted(_VALID_FORMATS))}.",
            file=sys.stderr,
        )
        sys.exit(2)
    cmd.append(f"--vip-format={','.join(requested)}")
    if args.interactive_auth:
        cmd.append("--interactive-auth")
    if args.headless_auth:
        cmd.append("--headless-auth")
    if args.no_auth:
        cmd.append("--no-auth")
    if args.api_auth:
        cmd.append("--api-auth")
    for ext in args.extensions or []:
        cmd.append(f"--vip-extensions={ext}")
    if args.categories:
        cmd.extend(["-m", _normalize_categories(args.categories)])
    else:
        cmd.extend(["-m", _default_marker_expr(_extra_keep_from_args(args))])
    if args.filter_expr:
        cmd.extend(["-k", args.filter_expr])

    if args.verbose:
        cmd.append("--vip-verbose")
        cmd.append("-s")

    # Default to a conservative parallel-by-group run so pip-installed users
    # get grouping too -- pyproject.toml's `addopts = "-n auto --dist
    # loadgroup"` only applies when pytest's rootdir is this repo. 2 workers
    # is a safe default: product tests log real sessions in against a shared
    # deployment and a single shared test account, and higher default
    # concurrency intermittently storms the OIDC IdP (`?error=2`) and exceeds
    # small deployments' concurrent-session capacity. Users raise it with
    # `-- -n N` when their deployment can handle more. Respect an explicit
    # user choice for either flag (including `-p no:xdist`, which disables
    # xdist and thus both).
    _set_n, _set_dist = _user_set_xdist(args.pytest_args)
    if not _set_n:
        cmd.extend(["-n", "2"])
    if not _set_dist:
        cmd.extend(["--dist", "loadgroup"])

    if getattr(args, "ci", False):
        cmd.append("--tb=short")

    cmd.extend(args.pytest_args)
    if args.headless_auth:
        # MFA prompting needs stdin; always append -s last so it
        # overrides any conflicting --capture args from user or verbose.
        cmd.append("-s")

    try:
        result = subprocess.run(cmd, timeout=args.test_timeout)
        sys.exit(result.returncode)
    except subprocess.TimeoutExpired:
        print(
            f"Error: tests timed out after {args.test_timeout} seconds. "
            "Increase with --test-timeout or investigate hung tests.",
            file=sys.stderr,
        )
        sys.exit(1)
    finally:
        if temp_config:
            Path(temp_config).unlink(missing_ok=True)


# Quarto report template files copied into the working report/ directory.
# Keep in sync with the force-include block in pyproject.toml.
_REPORT_TEMPLATE_FILES = ("index.qmd", "details.qmd", "_quarto.yml", "styles.css")


def _has_all_report_templates(directory: Path) -> bool:
    """Whether ``directory`` contains every required Quarto template file."""
    return all((directory / name).is_file() for name in _REPORT_TEMPLATE_FILES)


def _copy_report_templates(src: Path, report_dir: Path) -> list[str]:
    """Copy template files from ``src``, returning names whose content changed.

    Files already identical in ``report_dir`` are left untouched, and only
    pre-existing files that were overwritten with different content are
    reported (fresh copies into an empty directory are not).
    """
    import shutil

    replaced = []
    for name in _REPORT_TEMPLATE_FILES:
        candidate = src / name
        dest = report_dir / name
        if not candidate.is_file():
            continue
        if dest.is_file():
            if dest.read_bytes() == candidate.read_bytes():
                continue
            replaced.append(name)
        shutil.copy2(candidate, dest)
    return replaced


def _ensure_report_templates(report_dir: Path) -> bool:
    """Make sure the Quarto templates exist in ``report_dir``.

    Prefers the copy bundled in the installed wheel (``vip/_report``),
    refreshing ``report_dir`` from it on every run so an upgraded VIP renders
    its current templates. Falls back to the repo's top-level ``report/`` so
    in-repo usage and selftests work without building a wheel. Returns ``True``
    only when *all* of ``_REPORT_TEMPLATE_FILES`` are present in ``report_dir``,
    so a partial source (e.g. a template missing from one location) is topped
    up from the other rather than silently rendering a degraded report.

    Identical files are not rewritten, and a notice lists any existing files
    that the refresh did overwrite, so local template customizations never
    disappear silently.
    """
    import contextlib
    import importlib.resources

    replaced: list[str] = []

    # Bundled wheel copy: refresh templates into the working directory. Only
    # materializing the resource is guarded (OSError covers as_file() failures
    # on zip-imported packages before Python 3.12); a failure while copying
    # into report_dir must propagate, or a stale set already present there
    # would be rendered as if it were current.
    with contextlib.ExitStack() as stack:
        try:
            bundled = importlib.resources.files("vip") / "_report"
            p = stack.enter_context(importlib.resources.as_file(bundled))
        except (TypeError, OSError, ModuleNotFoundError):
            p = None
        if p is not None and _has_all_report_templates(p):
            replaced += _copy_report_templates(p, report_dir)

    # Source checkout: three levels up from src/vip/cli.py → repo root/report.
    if not _has_all_report_templates(report_dir):
        repo_report = Path(__file__).parent.parent.parent / "report"
        if _has_all_report_templates(repo_report) and repo_report.resolve() != report_dir.resolve():
            replaced += _copy_report_templates(repo_report, report_dir)

    if replaced:
        print(
            f"Refreshed report templates in {report_dir}: {', '.join(replaced)}",
            file=sys.stderr,
        )

    # True only if the working directory now has the complete set (from a
    # bundled/repo copy above, or from a prior run's copy already present).
    return _has_all_report_templates(report_dir)


def run_report(args: argparse.Namespace) -> None:
    """Render the Quarto report from a results.json file."""
    import shutil
    import webbrowser

    report_dir = Path("report")
    report_dir.mkdir(parents=True, exist_ok=True)

    results_src = Path(args.results)
    results_dest = report_dir / "results.json"

    if results_src.resolve() != results_dest.resolve():
        if not results_src.exists():
            print(f"Error: results file not found: {results_src}", file=sys.stderr)
            sys.exit(1)
        shutil.copy2(results_src, results_dest)
    elif not results_dest.exists():
        print(
            f"Error: no results found at {results_dest}. "
            "Run 'vip verify' first, or pass --results PATH.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not _ensure_report_templates(report_dir):
        print(
            "Error: could not locate the VIP report templates. "
            "Reinstall posit-vip so the bundled report is available.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        result = subprocess.run(["quarto", "render"], cwd=str(report_dir))
    except FileNotFoundError:
        print(
            "Error: quarto was not found on PATH. Install Quarto "
            "(https://quarto.org/docs/get-started/) and re-run.",
            file=sys.stderr,
        )
        sys.exit(1)

    if result.returncode != 0:
        sys.exit(result.returncode)

    output = report_dir / "_output" / "index.html"
    if not output.exists():
        print(
            "Error: no report was produced. Ensure Quarto is installed and the "
            "report extra is available (pip install 'posit-vip[report]').",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Report generated: {output}")
    if args.open:
        webbrowser.open(output.resolve().as_uri())


def _collect_status(config: VIPConfig) -> dict:
    """Run health checks and return structured status data.

    Returns a dict with the schema::

        {
            "products": {
                "connect":         {"configured": bool, "state": "ok"|"fail"|"skip", ...},
                "workbench":       {...},
                "package_manager": {...},
            },
            "outcome": "ok" | "fail",
            "exit_status": 0 | 1,
        }

    No printing or sys.exit side effects; callers handle rendering.
    """
    from vip.clients.connect import ConnectClient
    from vip.clients.packagemanager import PackageManagerClient
    from vip.clients.workbench import WorkbenchClient

    checks = [
        ("connect", config.connect),
        ("workbench", config.workbench),
        ("package_manager", config.package_manager),
    ]

    products: dict[str, dict] = {}
    for name, pc in checks:
        if not pc.is_configured:
            products[name] = {"configured": False, "state": "skip", "detail": "not configured"}
            continue
        try:
            if name == "connect":
                client: ConnectClient | WorkbenchClient | PackageManagerClient = ConnectClient(
                    pc.url,
                    pc.api_key,  # type: ignore[attr-defined]
                )
            elif name == "workbench":
                client = WorkbenchClient(pc.url, pc.api_key)  # type: ignore[attr-defined]
            else:
                client = PackageManagerClient(pc.url, pc.token)  # type: ignore[attr-defined]
            http_status = client.health()
            state = "ok" if http_status < 400 else "fail"
            products[name] = {
                "configured": True,
                "url": pc.url,
                "http_status": http_status,
                "state": state,
            }
        except Exception as e:
            products[name] = {
                "configured": True,
                "url": pc.url,
                "state": "fail",
                "detail": str(e),
            }

    all_ok = all(p["state"] in ("ok", "skip") for p in products.values())
    outcome = "ok" if all_ok else "fail"
    exit_status = 0 if all_ok else 1
    return {"products": products, "outcome": outcome, "exit_status": exit_status}


def run_status(args: argparse.Namespace) -> None:
    """Run preflight health checks against each configured product."""
    from vip.config import load_config

    config = load_config(args.config)
    data = _collect_status(config)

    if getattr(args, "json", False):
        print(json.dumps(data))
    else:
        for name, product in data["products"].items():
            state = product["state"]
            if state == "skip":
                detail = product.get("detail", "not configured")
            elif "http_status" in product:
                detail = f"HTTP {product['http_status']}"
            else:
                detail = product.get("detail", "")
            print(f"  {state.upper():4s}  {name:20s}  {detail}")

    sys.exit(data["exit_status"])


def run_install(args: argparse.Namespace) -> None:
    """Provision system packages and Playwright Chromium for VIP local mode."""
    from datetime import datetime, timezone

    from vip.install import platform as plat
    from vip.install.manifest import (
        SCHEMA_VERSION,
        Manifest,
        current_host,
        default_path,
        load,
    )
    from vip.install.packages import PackageQueryError, installed_dpkg, installed_rpm
    from vip.install.plan import build_install_plan
    from vip.install.playwright import PlaywrightInstallError, chromium_installed, default_cache_dir
    from vip.install.runner import execute_install_plan, format_install_plan

    info = plat.detect()
    manifest_path = default_path()
    manifest = load(manifest_path)

    cache_dir = default_cache_dir()

    try:
        plan = build_install_plan(
            platform_info=info,
            manifest=manifest,
            rpm_installed=installed_rpm,
            dpkg_installed=installed_dpkg,
            chromium_present=chromium_installed(cache_dir),
            playwright_cache_dir=cache_dir,
            skip_system=bool(getattr(args, "skip_system", False)),
        )

        if getattr(args, "dry_run", False):
            print(format_install_plan(plan), end="")
            return

        if manifest is None:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            from vip import __version__ as vip_version

            manifest = Manifest(
                version=SCHEMA_VERSION,
                vip_version=vip_version,
                created_at=now,
                updated_at=now,
                host=current_host(),
                platform=info.family,
                platform_id=info.id,
                platform_version=info.version,
            )

        rc = execute_install_plan(plan, manifest=manifest, manifest_path=manifest_path)
    except (PlaywrightInstallError, PackageQueryError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.exit(rc)


def run_uninstall(args: argparse.Namespace) -> None:
    """Reverse `vip install` using the manifest."""
    from vip.install.manifest import (
        ManifestError,
        current_host,
        default_path,
        load,
    )
    from vip.install.plan import build_uninstall_plan
    from vip.install.runner import execute_uninstall_plan

    manifest_path = default_path()
    try:
        manifest = load(manifest_path)
    except ManifestError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if manifest is None:
        print(
            f"No {manifest_path.name} found. Nothing to uninstall, or vip was "
            "installed by a different mechanism.",
            file=sys.stderr,
        )
        sys.exit(1)

    if manifest.host != current_host() and not getattr(args, "force_host", False):
        print(
            f"Error: manifest host {manifest.host!r} does not match current host "
            f"{current_host()!r}. Pass --force-host to override.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Resolve Connect URL for chained cleanup.
    connect_url = getattr(args, "connect_url", None)
    if not connect_url:
        if sys.version_info >= (3, 11):
            import tomllib as _tomllib
        else:
            import tomli as _tomllib  # type: ignore[no-redef]

        cfg = None
        try:
            from vip.config import load_config

            cfg = load_config()
        except (_tomllib.TOMLDecodeError, ValueError) as exc:
            print(
                f"warning: failed to load vip.toml for chained cleanup: {exc}; "
                "continuing without chained Connect cleanup",
                file=sys.stderr,
            )
        if cfg and cfg.connect and cfg.connect.url:
            connect_url = cfg.connect.url

    plan = build_uninstall_plan(
        manifest=manifest,
        connect_url=connect_url,
    )

    cleanup_callable = None
    if connect_url:
        api_key = getattr(args, "api_key", None) or os.environ.get("VIP_CONNECT_API_KEY", "")

        def cleanup_callable(url: str) -> None:  # noqa: F811
            from vip.clients.connect import ConnectClient

            with ConnectClient(url, api_key) as client:
                client.cleanup_vip_content()

    rc = execute_uninstall_plan(
        plan,
        manifest_path=manifest_path,
        yes=bool(getattr(args, "yes", False)),
        cleanup_callable=cleanup_callable,
    )
    sys.exit(rc)


def run_scaffold(args: argparse.Namespace) -> None:
    """Copy the cross_product_validation example to a user-specified directory."""
    import importlib.resources
    import shutil

    # Prefer the bundled copy inside the installed wheel (_scaffold/ is embedded
    # via [tool.hatch.build.targets.wheel.force-include]).  Fall back to the
    # repo's top-level examples/ directory so in-repo usage and selftests work
    # without building a wheel first.
    src: Path | None = None
    try:
        scaffold_pkg = importlib.resources.files("vip") / "_scaffold" / "cross_product_validation"
        # files() returns a Traversable; we need a real Path for shutil.copytree.
        with importlib.resources.as_file(scaffold_pkg) as p:
            if p.is_dir():
                src = p
    except (TypeError, FileNotFoundError):
        pass

    if src is None:
        # Source checkout: three levels up from src/vip/cli.py → repo root.
        repo_root = Path(__file__).parent.parent.parent
        candidate = repo_root / "examples" / "cross_product_validation"
        if candidate.is_dir():
            src = candidate

    if src is None:
        print(
            "Error: could not locate examples/cross_product_validation/. "
            "Ensure VIP is installed from source or as a wheel built with examples.",
            file=sys.stderr,
        )
        sys.exit(1)

    dest = Path(args.output)
    if dest.exists() and not args.force:
        print(
            f"Error: destination already exists: {dest}\nPass --force to overwrite.",
            file=sys.stderr,
        )
        sys.exit(1)

    if dest.exists():
        if dest.is_dir() and not dest.is_symlink():
            shutil.rmtree(dest)
        else:
            dest.unlink()

    shutil.copytree(src, dest)
    print(f"Scaffolded extension to: {dest}")
    print(
        f"\nNext steps:\n"
        f"  1. Edit {dest / 'conftest.py'} to set your package names and versions.\n"
        f"  2. Add a [runtimes] block to vip.toml:\n"
        f"       [runtimes]\n"
        f'       r_versions = ["4.4.0"]\n'
        f'       python_versions = ["3.11.0"]\n'
        f"  3. Run the extension:\n"
        f"       vip verify --config vip.toml --extensions {dest}\n"
        f"\nSee {dest / 'README.md'} for full customization instructions."
    )


def _cleanup_workbench_sessions(
    workbench_url: str,
    args: argparse.Namespace,
    config: VIPConfig,
) -> None:
    """Authenticate to Workbench and quit orphaned VIP-named sessions.

    API-first: quits via :meth:`~vip.clients.workbench.WorkbenchClient.quit_vip_sessions`
    when the session API is reachable. Escalates to a browser-driven UI sweep
    (:func:`vip.workbench_ui.quit_vip_sessions_via_ui`) when the API is
    unreachable *or* VIP sessions remain after the API sweep — a reachable API
    whose DELETE/suspend call is a silent no-op is exactly the #467 bug, so a
    "no error" response is not trusted on its own.

    Authentication is cache-aware: reuses a storage state saved by a prior
    ``vip verify`` run (same cache path, <4h old) when available. Uses
    ``--headless-auth``'s flow when ``VIP_TEST_USERNAME``/``VIP_TEST_PASSWORD``
    are set, otherwise opens an interactive browser login. Never lets an
    authentication failure crash with a bare traceback — prints an actionable
    error and exits 1.
    """
    from vip.auth import (
        AuthConfigError,
        authenticated_page,
        start_headless_auth,
        start_interactive_auth,
    )
    from vip.clients.workbench import WorkbenchClient
    from vip.workbench_ui import quit_vip_sessions_via_ui

    insecure = config.insecure
    ca_bundle = config.ca_bundle
    # Mirrors plugin.py's cache path (Path(config.rootpath) / ".vip-auth-cache.json"):
    # there is no pytest config here, so the invocation directory stands in for
    # rootpath, matching where a prior `vip verify` run from the same directory
    # would have written its cache.
    cache_path = Path.cwd() / ".vip-auth-cache.json"

    username = config.auth.username
    password = config.auth.password

    try:
        if username and password:
            session = start_headless_auth(
                workbench_url=workbench_url,
                provider=config.auth.provider,
                username=username,
                password=password,
                idp=config.auth.idp,
                cache_path=cache_path,
                insecure=insecure,
                ca_bundle=ca_bundle,
            )
        else:
            session = start_interactive_auth(
                workbench_url=workbench_url,
                cache_path=cache_path,
                insecure=insecure,
                ca_bundle=ca_bundle,
            )
    except AuthConfigError as exc:
        print(f"Error: could not authenticate to Workbench: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(
            f"Error: could not authenticate to Workbench at {workbench_url}: {exc}\n"
            "Set VIP_TEST_USERNAME and VIP_TEST_PASSWORD for non-interactive cleanup, "
            "or run this command where a browser can open for an interactive login.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        print(f"Cleaning up orphaned Workbench sessions at {workbench_url}")
        cookies = session.load_cookies()
        client = WorkbenchClient(
            workbench_url, cookies=cookies, insecure=insecure, ca_bundle=ca_bundle
        )
        try:
            api_reachable = client.sessions_api_reachable()
            if api_reachable:
                quit_count = client.quit_vip_sessions()
                print(f"Quit {quit_count} VIP Workbench session(s) via the API")
                remaining = client.count_vip_sessions()
            else:
                remaining = -1  # unknown — escalate below

            # Escalate when the API is unreachable, when VIP sessions remain, or
            # when the count is undeterminable (-1). Only a confirmed 0 skips the
            # UI sweep, so an unparseable API response can never silently orphan
            # sessions (issue #467).
            if not api_reachable or remaining != 0:
                print("Escalating to browser-driven session cleanup ...")
                with authenticated_page(session, insecure=insecure, ca_bundle=ca_bundle) as page:
                    ui_count = quit_vip_sessions_via_ui(page, workbench_url)
                print(f"Quit {ui_count} VIP Workbench session(s) via the UI")
        finally:
            client.close()
    finally:
        session.cleanup()


def _ensure_cli_logging() -> None:
    """Route ``vip.*`` INFO/WARNING logs to stderr for the cleanup command.

    The session-cleanup path (WorkbenchClient + workbench_ui) emits progress
    and "sessions still present" warnings via ``logging``; without a handler
    those are invisible (or only WARNING via the lastResort handler). Attach a
    single stderr handler to the ``vip`` logger so ``vip cleanup`` surfaces
    what it did. Idempotent: only configures once.
    """
    vip_logger = logging.getLogger("vip")
    if not vip_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        vip_logger.addHandler(handler)
        vip_logger.setLevel(logging.INFO)
        vip_logger.propagate = False


def _load_cleanup_config() -> VIPConfig:
    """Load ``vip.toml`` if present, else a default ``VIPConfig``.

    ``load_config`` warns when no config file exists, which is noise for
    ``vip cleanup`` when the user passes URLs explicitly and has no
    ``vip.toml``. This loads the file only when it actually exists; otherwise
    it returns a default ``VIPConfig`` whose ``__post_init__`` still picks up
    env-based credentials (``VIP_TEST_USERNAME``/``VIP_TEST_PASSWORD``,
    ``VIP_WORKBENCH_API_KEY``, etc.).
    """
    from vip.config import VIPConfig, load_config

    env = os.environ.get("VIP_CONFIG")
    path = Path(env) if env else Path("vip.toml")
    if path.exists():
        return load_config()
    return VIPConfig()


def run_cleanup(args: argparse.Namespace) -> None:
    """Delete VIP test content from Connect and quit orphaned Workbench sessions.

    Connect cleanup deletes all content tagged ``_vip_test``. Workbench
    cleanup quits VIP-named sessions (see
    :func:`vip.clients.workbench.is_vip_session`), escalating to a
    browser-driven UI sweep when the session API is unreachable or sessions
    persist despite the API reporting success. The Connect/Workbench URLs
    come from ``--connect-url``/``--workbench-url`` or, if omitted, from
    ``[connect] url``/``[workbench] url`` in ``vip.toml``. At least one of
    the two must resolve.
    """
    _ensure_cli_logging()
    connect_url = getattr(args, "connect_url", None)
    api_key = getattr(args, "api_key", None) or os.environ.get("VIP_CONNECT_API_KEY", "")
    workbench_url = getattr(args, "workbench_url", None)

    # Load vip.toml when present to fill in any URL not passed on the CLI, and
    # to supply TLS/auth settings for the Workbench path. Loaded quietly: an
    # explicit `vip cleanup --connect-url ...` with no vip.toml must not emit a
    # "Config file not found" warning (env-based credentials still apply).
    config = _load_cleanup_config()
    if not connect_url and config.connect and config.connect.url:
        connect_url = config.connect.url
    if not workbench_url and config.workbench and config.workbench.url:
        workbench_url = config.workbench.url

    if not connect_url and not workbench_url:
        print(
            "Error: no Connect or Workbench URL found. Pass --connect-url / "
            "--workbench-url, or set [connect] url / [workbench] url in vip.toml.",
            file=sys.stderr,
        )
        sys.exit(1)

    if connect_url:
        from vip.clients.connect import ConnectClient

        print(f"Cleaning up VIP test content on Connect at {connect_url}")
        with ConnectClient(connect_url, api_key) as client:
            deleted = client.cleanup_vip_content()
        print(f"Deleted {deleted} VIP test content item(s)")

    if workbench_url:
        _cleanup_workbench_sessions(workbench_url, args, config)

    print("Cleanup completed successfully")


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


def _format_version_details() -> str:
    """Render the vip version and the minimum supported Posit Team release."""
    from vip import __version__
    from vip.version import MINIMUM_SUPPORTED_POSIT_TEAM

    return (
        f"vip {__version__}\nMinimum supported Posit Team version: {MINIMUM_SUPPORTED_POSIT_TEAM}"
    )


def run_version(args: argparse.Namespace) -> None:
    """Print the vip version and the minimum supported Posit Team version."""
    print(_format_version_details())


def main() -> None:
    """Main entry point for the VIP CLI."""
    from vip import __version__

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
        'Presence implies provider = "oidc" unless overridden in vip.toml.',
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
        help="CI preset: emit json,junit,sarif, use concise tracebacks, and run"
        " strictly non-interactively.",
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
            "Copy the cross_product_validation example to a new directory, ready to\n"
            "customise and run with:\n\n"
            "  vip verify --config vip.toml --extensions <output-dir>\n\n"
            "The example verifies specific R/Python runtime versions and package\n"
            "installability across Workbench and Connect. Edit the generated\n"
            "conftest.py to set your own package names and version requirements.\n\n"
            "See vip.toml.example for the [runtimes] block you need to populate."
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
    args.func(args)


if __name__ == "__main__":
    main()
