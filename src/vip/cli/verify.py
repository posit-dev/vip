"""``vip verify``: run the VIP test suite against URL args or a vip.toml config."""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from importlib.util import find_spec
from pathlib import Path

from vip.bundle.summary import authority_url
from vip.cli._common import _resolve_effective_ca_bundle
from vip.config import ProductConfig, VIPConfig, load_config
from vip.errors import (
    ConfigError,
    VipError,
)
from vip.output import VERBOSITY_ENV_VAR, get_verbosity, info
from vip.proxy import proxy_env_for_subprocess
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
# Pre-flight checks on the resolved config
# ---------------------------------------------------------------------------


def _print_skip_notes(cfg: VIPConfig) -> None:
    """Print a note for each product that is not configured."""
    products = [
        ("Connect", cfg.connect),
        ("Workbench", cfg.workbench),
        ("Package Manager", cfg.package_manager),
    ]
    for name, pc in products:
        if not pc.is_configured:
            reason = "disabled" if not pc.enabled else "no URL given"
            info(f"Note: {name} {reason} — {name} tests will not be collected.")


def _check_credentials(
    cfg: VIPConfig,
    *,
    interactive_auth: bool,
    categories: str | None,
) -> None:
    """Exit early when products are configured but credentials are missing.

    When *categories* is provided, only check products whose marker appears
    in the expression.  Without categories all configured products are checked.
    """
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


def _config_idp(cfg: VIPConfig) -> str:
    """Return the normalized ``[auth] idp`` of the resolved config.

    Normalized (stripped, lowercased) to match ``idp.get_idp_strategy``.
    """
    return (cfg.auth.idp or "").strip().lower()


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


_PRODUCTS = ("connect", "workbench", "package_manager")

# Flags that override the config file; any one of them means a temp config is needed.
_OVERRIDE_FLAGS = (
    "connect_url",
    "workbench_url",
    "package_manager_url",
    "connect_version",
    "workbench_version",
    "package_manager_version",
    "idp",
    "provider",
    "insecure",
    "ca_bundle",
    "proxy",
)


def _has_overrides(args: argparse.Namespace) -> bool:
    return args.no_proxy is not None or any(getattr(args, f, None) for f in _OVERRIDE_FLAGS)


def _base_identity(base: Path) -> dict:
    """Return the deployment name and product URLs (no userinfo) that *base* declares.

    Each URL is normalized the way ``load_config`` does and reduced to its host
    and port. A URL whose host could be part of a secret is marked ``ambiguous``.

    ``vip bundle`` compares these with the config file it is given, so a flag
    that replaced a product URL does not hide which file the run started from.
    """
    raw = tomllib.loads(base.read_text(encoding="utf-8"))
    general = raw.get("general")
    name = general.get("deployment_name") if isinstance(general, dict) else None
    products = {}
    for product in _PRODUCTS:
        table = raw.get(product)
        url = table.get("url") if isinstance(table, dict) else None
        url = ProductConfig(url=url).url if isinstance(url, str) else ""
        authority = authority_url(url)
        products[product] = (
            {"url": authority} if authority is not None else {"url": "", "ambiguous": True}
        )
    return {
        "deployment_name": name if isinstance(name, str) else "Posit Team",
        "products": products,
    }


def _toml_string(value: str) -> str:
    """Quote a TOML basic string: JSON escapes, but raw UTF-8 (no surrogates) and DEL escaped."""
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007F")


def _toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else _toml_string(key)


def _toml_value(value: object) -> str:
    """Render a value ``tomllib`` can produce as TOML (JSON string escapes are valid TOML)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return (
            "{ " + ", ".join(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in value.items()) + " }"
        )
    raise TypeError(f"cannot write {type(value).__name__} to TOML")


def _toml_lines(table: dict, path: tuple[str, ...] = ()) -> list[str]:
    lines = ["[" + ".".join(_toml_key(k) for k in path) + "]"] if path else []
    lines += [
        f"{_toml_key(k)} = {_toml_value(v)}" for k, v in table.items() if not isinstance(v, dict)
    ]
    lines.append("")
    for key, value in table.items():
        if isinstance(value, dict):
            lines += _toml_lines(value, (*path, key))
    return lines


def _dump_toml(raw: dict) -> str:
    """Serialize the nested dict ``tomllib`` returns back to TOML text."""
    return "\n".join(_toml_lines(raw))


def _default_config_path() -> Path:
    env = os.environ.get("VIP_CONFIG")
    return Path(env) if env else Path("vip.toml")


def _resolve_base_path(args: argparse.Namespace) -> Path | None:
    """Return the config file ``vip verify`` starts from, or None in URL mode.

    URL mode is product-URL flags with no ``--config``: the run starts from
    defaults instead of a config file.
    """
    if args.config:
        path = Path(args.config)
        if not path.is_file():
            raise ConfigError(f"config file not found: {args.config}")
        return path.resolve()
    if args.connect_url or args.workbench_url or args.package_manager_url:
        return None
    default = _default_config_path()
    if not default.is_file():
        raise ConfigError(
            f"config file not found: {default}\n"
            "Provide a config file with --config, or pass product URLs directly "
            "(e.g. --connect-url https://connect.example.com)."
        )
    # Pin the resolved default so pytest loads the same file the CLI validated,
    # regardless of pytest's rootdir or subprocess CWD.
    return default.resolve()


def _table(raw: dict, key: str) -> dict:
    """Return ``raw[key]``, creating it when absent; a non-table value is a config error."""
    table = raw.setdefault(key, {})
    if not isinstance(table, dict):
        raise ConfigError(f"[{key}] must be a table, got {type(table).__name__}")
    return table


def _inherited_auth() -> dict:
    """Return provider/idp from the default config file, best-effort.

    Lets ``vip verify --workbench-url ... --headless-auth`` pick up the ``[auth]``
    section already configured; a malformed vip.toml must not break a URL-driven run.
    """
    path = _default_config_path()
    try:
        auth = (
            tomllib.loads(path.read_text(encoding="utf-8")).get("auth", {})
            if path.is_file()
            else {}
        )
    except (OSError, ValueError):
        return {}
    if not isinstance(auth, dict):
        return {}
    return {k: auth[k] for k in ("provider", "idp") if k in auth}


def _override_products(raw: dict, args: argparse.Namespace, *, url_mode: bool) -> None:
    """Apply product URL and version flags; in URL mode a product without a URL is disabled."""
    for product in _PRODUCTS:
        url = getattr(args, f"{product}_url", None)
        version = getattr(args, f"{product}_version", None)
        if url:
            table = _table(raw, product)
            table["url"] = url
            table.pop("enabled", None)
        elif url_mode:
            raw[product] = {"enabled": False}
            continue
        if version:
            _table(raw, product)["version"] = version


def _override_auth(raw: dict, args: argparse.Namespace) -> None:
    """Resolve provider/idp from the flags and the file's ``[auth]``.

    - An explicit --provider always wins, over --idp's implied "oidc" and the file.
    - Otherwise, with an idp set, keep an inherited IdP-class provider (saml/oauth2)
      so specific declarations survive, but replace a non-IdP one (ldap, password)
      with "oidc": vip.auth's flow selection keys off provider, not idp.
    - Without --provider or an idp, honour whatever the file declared.
    """
    auth = _table(raw, "auth")
    idp = getattr(args, "idp", None) or auth.get("idp")
    inherited = auth.get("provider")
    if inherited == "password":
        inherited = None
    explicit = getattr(args, "provider", None)
    if explicit:
        provider = explicit
    elif idp:
        provider = inherited if inherited in _IDP_PROVIDERS else "oidc"
    else:
        provider = inherited
    if provider:
        auth["provider"] = provider
    if idp:
        auth["idp"] = idp
    if not auth:
        del raw["auth"]


def _override_tls(raw: dict, args: argparse.Namespace) -> None:
    insecure = getattr(args, "insecure", False)
    ca_bundle = getattr(args, "ca_bundle", None)
    if not (insecure or ca_bundle):
        return
    tls = _table(raw, "tls")
    insecure = insecure or tls.get("insecure", False)
    ca = ca_bundle or tls.get("ca_bundle")
    ca = _resolve_effective_ca_bundle(insecure, Path(ca) if ca else None)
    tls.pop("ca_bundle", None)
    if insecure:
        tls["insecure"] = True
    if ca:
        tls["ca_bundle"] = str(ca)


def _override_proxy(raw: dict, args: argparse.Namespace) -> None:
    """Apply --proxy/--no-proxy to ``[proxy]``.

    --no-proxy replaces the file's bypass list, even with an empty one. With no
    --proxy, an empty --no-proxy turns proxying off (``enabled = false``) and drops
    the file's url and bypass list, forcing every request direct regardless of the
    ambient environment.
    """
    proxy_url = getattr(args, "proxy", None)
    no_proxy = getattr(args, "no_proxy", None)
    if not (proxy_url or no_proxy is not None):
        return
    hosts = [h.strip() for h in no_proxy.split(",") if h.strip()] if no_proxy else []
    proxy = _table(raw, "proxy")
    if not proxy_url and not hosts:
        proxy.pop("url", None)
        proxy.pop("no_proxy", None)
        proxy["enabled"] = False
        return
    proxy.pop("enabled", None)
    if proxy_url:
        proxy["url"] = proxy_url
    if no_proxy is not None:
        proxy["no_proxy"] = hosts


def _generate_temp_config(args: argparse.Namespace, base: Path | None = None) -> str:
    """Write the base config with the CLI flags applied to a temp TOML; return its path.

    The file's raw TOML is merged with the flags, not the loaded config, so values
    resolved from the environment (API keys, passwords, ``*_env`` indirection) are
    never written out. Relative paths such as ``ca_bundle`` resolve against the
    working directory either way, which the pytest subprocess shares.
    """
    url_mode = base is None
    raw = {"auth": _inherited_auth()} if base is None else tomllib.loads(base.read_text("utf-8"))
    _override_products(raw, args, url_mode=url_mode)
    if url_mode or getattr(args, "idp", None) or getattr(args, "provider", None):
        _override_auth(raw, args)
    _override_tls(raw, args)
    _override_proxy(raw, args)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False, encoding="utf-8") as f:
        f.write(_dump_toml(raw))
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

    base = _resolve_base_path(args)
    has_overrides = _has_overrides(args)
    temp_config = None
    try:
        try:
            temp_config = _generate_temp_config(args, base) if has_overrides else None
            url_overridden = any(getattr(args, f"{p}_url", None) for p in _PRODUCTS)
            base_identity = _base_identity(base) if base and url_overridden else None
            config_path = temp_config or str(base)
            cfg = load_config(config_path)
        except (ValueError, AttributeError, TypeError) as exc:
            # A table of the wrong shape makes load_config raise AttributeError or TypeError.
            raise ConfigError(str(exc)) from exc
        _run_pytest(args, cfg, config_path, base_identity)
    finally:
        if temp_config:
            Path(temp_config).unlink(missing_ok=True)


def _run_pytest(
    args: argparse.Namespace, cfg: VIPConfig, config_path: str, base_identity: dict | None
) -> None:
    """Pre-flight checks, then run pytest against *config_path* (the resolved *cfg*)."""
    if args.interactive_auth and args.headless_auth:
        raise ConfigError("--interactive-auth and --headless-auth are mutually exclusive.")

    if args.no_auth and args.api_auth:
        raise ConfigError("--no-auth and --api-auth are mutually exclusive.")

    if getattr(args, "ci", False) and (args.interactive_auth or args.headless_auth):
        raise ConfigError(
            "--ci requires non-interactive execution and cannot be combined "
            "with --interactive-auth/--headless-auth."
        )

    if args.api_auth and _config_idp(cfg) == "snowflake":
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
    _print_skip_notes(cfg)
    if not args.no_auth and not args.api_auth:
        _check_credentials(
            cfg,
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

    cmd.append(f"--vip-config={config_path}")
    if base_identity is not None:
        cmd.append(f"--vip-base={json.dumps(base_identity)}")
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
    # read the config directly.
    subprocess_env = proxy_env_for_subprocess(cfg.proxy, os.environ)
    # The pytest plugin's auth code reads the level from the environment.
    subprocess_env[VERBOSITY_ENV_VAR] = get_verbosity().name.lower()

    try:
        result = subprocess.run(cmd, timeout=args.test_timeout, env=subprocess_env, check=False)
        sys.exit(result.returncode)
    except subprocess.TimeoutExpired:
        raise VipError(
            f"tests timed out after {args.test_timeout} seconds. "
            "Increase with --test-timeout or investigate hung tests."
        ) from None
