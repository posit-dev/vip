"""``vip verify``: run the VIP test suite against URL args or a vip.toml config."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from importlib.util import find_spec
from pathlib import Path

from vip.cli._common import _resolve_effective_ca_bundle
from vip.errors import (
    ConfigError,
    VipError,
)
from vip.reporting import VALID_FORMATS
from vip.timeouts import scaled

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

# Auth providers that imply IdP-based auth (used by both --idp's implied
# default and --provider's own validation). Mirrors vip.auth.flows' own
# _IDP_PROVIDERS, kept as a separate tuple here so vip.cli doesn't need to
# import vip.auth (and its playwright dependency) at module load time.
_IDP_PROVIDERS = ("oidc", "saml", "oauth2")


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
        raise ConfigError(
            f"unknown category '{word}'. Valid categories: {_valid_categories_message()}"
        )

    result = _IDENT_RE.sub(_replace, expr)
    # After substitution, only whitespace and parentheses should remain
    # between identifiers.  Any leftover characters (digits, underscores
    # from malformed tokens like ``_connect`` or ``1connect``) are invalid.
    leftover = _IDENT_RE.sub("", result).replace("(", "").replace(")", "").strip()
    if leftover:
        raise ConfigError(
            f"invalid characters in category expression: '{expr}'. "
            f"Valid categories: {_valid_categories_message()}"
        )
    return result


# ---------------------------------------------------------------------------
# Config generation from CLI URL args
# ---------------------------------------------------------------------------


def _print_skip_notes(config_path: str | None) -> None:
    """Print a note for each product that is not configured."""
    from vip.config import load_config

    try:
        cfg = load_config(config_path)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    products = [
        ("Connect", cfg.connect),
        ("Workbench", cfg.workbench),
        ("Package Manager", cfg.package_manager),
    ]
    for name, pc in products:
        if not pc.is_configured:
            reason = "disabled" if not pc.enabled else "no URL given"
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
        raise ConfigError(str(exc)) from exc
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
        raise ConfigError(
            f"{products} tests selected but no credentials provided.\n"
            "Set VIP_TEST_USERNAME and VIP_TEST_PASSWORD (optionally with --headless-auth),\n"
            "or use --interactive-auth, or --no-auth to skip tests that require "
            "authentication."
        )


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
        if a.startswith(("--dist", "no:xdist")) or a == "no:xdist":
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
        except Exception:  # noqa: BLE001
            existing = None
        if existing is not None:
            if not idp and existing.auth.idp:
                idp = existing.auth.idp
            if existing.auth.provider and existing.auth.provider != "password":
                inherited_provider = existing.auth.provider

    # Resolve the provider:
    # - An explicit --provider always wins, overriding both --idp's implied
    #   "oidc" and anything inherited from vip.toml.
    # - Otherwise, with --idp set, the user wants IdP-based auth.  Keep an
    #   inherited IdP-class value (saml/oauth2) so specific declarations
    #   survive; but ignore inherited non-IdP providers (ldap) that would
    #   contradict the CLI intent — vip.auth's flow selection keys off
    #   provider, not idp.
    # - Without --provider or --idp, just honour whatever vip.toml declared.
    explicit_provider = getattr(args, "provider", None)
    if explicit_provider:
        auth_provider: str | None = explicit_provider
    elif idp:
        auth_provider = inherited_provider if inherited_provider in _IDP_PROVIDERS else "oidc"
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
    effective_ca_bundle = _resolve_effective_ca_bundle(insecure, ca_bundle)
    if insecure or effective_ca_bundle:
        lines.append("[tls]")
        if insecure:
            lines.append("insecure = true")
        if effective_ca_bundle:
            lines.append(f"ca_bundle = {json.dumps(str(effective_ca_bundle))}")
        lines.append("")

    # Proxy: --proxy sets an explicit proxy URL; --no-proxy lists bypass hosts.
    # An empty --no-proxy with no --proxy means "proxying off" (enabled=false),
    # which forces every request direct regardless of the ambient environment.
    proxy_url = getattr(args, "proxy", None)
    no_proxy = getattr(args, "no_proxy", None)
    if proxy_url or no_proxy is not None:
        # Parse the bypass list once, stripping tokens; a value that is empty or
        # only whitespace/commas yields no hosts.
        hosts = [h.strip() for h in no_proxy.split(",") if h.strip()] if no_proxy else []
        lines.append("[proxy]")
        if proxy_url:
            lines.append(f"url = {json.dumps(proxy_url)}")
        elif not hosts:
            # No proxy URL and no bypass hosts (--no-proxy '' or whitespace-only):
            # disable proxying entirely, ignoring any ambient proxy env vars.
            lines.append("enabled = false")
        if hosts:
            lines.append(f"no_proxy = {json.dumps(hosts)}")
        lines.append("")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write("\n".join(lines) + "\n")
        return f.name


# ---------------------------------------------------------------------------
# vip verify
# ---------------------------------------------------------------------------


def run_verify(args: argparse.Namespace) -> None:
    """Run VIP tests locally against URL args or a vip.toml config."""
    provider = getattr(args, "provider", None)
    if provider and provider not in _IDP_PROVIDERS:
        raise ConfigError(
            f"unknown --provider value: {provider}. Valid: {', '.join(_IDP_PROVIDERS)}.",
            exit_code=2,
        )

    config_path = args.config
    temp_config = None

    proxy_flag_set = getattr(args, "proxy", None) or getattr(args, "no_proxy", None) is not None
    if not config_path and (args.connect_url or args.workbench_url or args.package_manager_url):
        temp_config = _generate_temp_config(args)
        config_path = temp_config
    elif proxy_flag_set:
        # --proxy/--no-proxy are only woven into the generated temp config (via
        # _generate_temp_config); any run that loads a config file instead has no
        # consumer for them, so the pytest subprocess would load the file's
        # [proxy] (or none) and silently ignore the flags. This mirrors
        # --insecure/--ca-bundle on the same branch. Rather than swallow the
        # flag, tell the user how to make it take effect. (Ambient
        # HTTP(S)_PROXY still works on a config run.)
        #
        # Keyed on "no temp config was generated", NOT on ``config_path``: the
        # default-resolution path (a ./vip.toml with no --config and no URL
        # flags -- the documented normal setup) still has config_path=None here
        # and would slip through a ``config_path and ...`` test entirely.
        print(
            ">>> Warning: --proxy/--no-proxy are ignored when a config file is used. "
            "Put the proxy under a [proxy] section in your config file "
            "(url = ..., no_proxy = [...], or enabled = false), or set "
            "HTTP_PROXY/HTTPS_PROXY/NO_PROXY in the environment.",
            file=sys.stderr,
        )

    # Fail fast when a config file is expected but doesn't exist.
    if config_path and not Path(config_path).is_file():
        raise ConfigError(f"config file not found: {config_path}")
    if not config_path:
        # No explicit config and no URL args — check the default resolution.
        env = os.environ.get("VIP_CONFIG")
        default = Path(env) if env else Path("vip.toml")
        if not default.is_file():
            raise ConfigError(
                f"config file not found: {default}\n"
                "Provide a config file with --config, or pass product URLs directly "
                "(e.g. --connect-url https://connect.example.com)."
            )
        # Pin the resolved default so pytest loads the same file the CLI
        # validated, regardless of pytest's rootdir or subprocess CWD.
        config_path = str(default.resolve())

    # Resolve explicit paths too so --vip-config always gets an absolute path.
    config_path = str(Path(config_path).resolve())

    if args.interactive_auth and args.headless_auth:
        raise ConfigError("--interactive-auth and --headless-auth are mutually exclusive.")

    if args.no_auth and args.api_auth:
        raise ConfigError("--no-auth and --api-auth are mutually exclusive.")

    if getattr(args, "ci", False) and (args.interactive_auth or args.headless_auth):
        raise ConfigError(
            "--ci requires non-interactive execution and cannot be combined "
            "with --interactive-auth/--headless-auth."
        )

    if args.api_auth and _config_idp(config_path) == "snowflake":
        raise ConfigError(
            "--api-auth is not supported with the Snowflake identity provider.\n"
            "A Posit Team Native App authenticates through the Snowpark Container "
            "Services ingress and has no standalone product API key for --api-auth to "
            "use.\n"
            "Use --headless-auth to run the full suite, or --no-auth for the stateless "
            "checks that do not require a login."
        )

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
        _spec = find_spec("vip_tests")
        if _spec and _spec.submodule_search_locations:
            cmd.append(_spec.submodule_search_locations[0])

    if config_path:
        cmd.append(f"--vip-config={config_path}")
    if args.report:
        cmd.append(f"--vip-report={args.report}")

    fmt = "json,junit,sarif" if getattr(args, "ci", False) else getattr(args, "format", "json")
    requested = [f.strip().lower() for f in fmt.split(",") if f.strip()]
    unknown = [f for f in requested if f not in VALID_FORMATS]
    if unknown:
        raise ConfigError(
            f"unknown --format value(s): {', '.join(unknown)}. "
            f"Valid: {', '.join(sorted(VALID_FORMATS))}.",
            exit_code=2,
        )
    cmd.append(f"--vip-format={','.join(requested)}")
    if args.interactive_auth:
        cmd.append("--interactive-auth")
    if args.headless_auth:
        cmd.append("--headless-auth")
    if args.no_auth:
        cmd.append("--no-auth")
    if args.api_auth:
        cmd.append("--api-auth")
    if getattr(args, "allow_unproven", False):
        cmd.append("--vip-allow-unproven")
    cmd.extend(f"--vip-extensions={ext}" for ext in args.extensions or [])
    if args.categories:
        marker_expr = _normalize_categories(args.categories)
    else:
        marker_expr = _default_marker_expr(_extra_keep_from_args(args))
    if getattr(args, "basic", False):
        marker_expr = f"({marker_expr}) and not slow" if marker_expr else "not slow"
    cmd.extend(["-m", marker_expr])
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

    # Reconcile the child environment with the resolved proxy so the
    # env-honoring egress in the suites (bare httpx.get probes, the load engine,
    # Chromium's own detection) takes the same route as the pooled clients that
    # read the config directly. Without this an explicit [proxy] url proxies the
    # clients but not the probes, and enabled=false disables the clients while
    # the probes stay on the ambient proxy. Best-effort: any config-load error
    # falls through to the ambient environment unchanged (env=None).
    subprocess_env: dict[str, str] | None = None
    if config_path:
        try:
            from vip.config import load_config
            from vip.proxy import proxy_env_for_subprocess

            subprocess_env = proxy_env_for_subprocess(load_config(config_path).proxy, os.environ)
        except Exception:  # noqa: BLE001
            subprocess_env = None

    try:
        result = subprocess.run(cmd, timeout=args.test_timeout, env=subprocess_env, check=False)
        sys.exit(result.returncode)
    except subprocess.TimeoutExpired:
        raise VipError(
            f"tests timed out after {args.test_timeout} seconds. "
            "Increase with --test-timeout or investigate hung tests."
        ) from None
    finally:
        if temp_config:
            Path(temp_config).unlink(missing_ok=True)
