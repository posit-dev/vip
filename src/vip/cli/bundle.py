"""``vip bundle``: write a zip of the report output, checked for known credentials."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vip import __version__
from vip.auth.cache import AUTH_CACHE_FILENAME, auth_cache_path
from vip.bundle.archive import (
    Collected,
    collect_members,
    find_secret_hits,
    short_secret_labels,
    write_zip,
)
from vip.bundle.summary import (
    auth_cache_secrets,
    build_config_summary,
    secret_values,
    strip_url_userinfo,
)
from vip.cli.report import _resolve_report_dir
from vip.cli.version import _format_version_details
from vip.config import VIPConfig, load_config
from vip.errors import BundleError

_PRODUCTS = ("connect", "workbench", "package_manager")


def _invocation_root(results: str | None) -> Path:
    """Return the directory that holds ``vip.toml``, ``report/``, and the legacy auth cache.

    With ``--results <dir>/report/results.json``, the root is ``<dir>``.
    Otherwise it is the working directory. ``_resolve_report_dir`` treats a
    working directory named ``report`` as the report directory itself, so the
    root is then one level up.
    """
    if results:
        parent = Path(results).resolve().parent
        if parent.name == "report":
            return parent.parent
    cwd = Path.cwd()
    return cwd.parent if cwd.name == "report" else cwd


def _report_dir(results: str | None) -> Path:
    """Return the report directory, as a path in the form that the user typed.

    With ``--results <dir>/report/results.json``, it is ``<dir>/report``, so
    that the rendered files of that run are found from any directory.
    """
    if results and Path(results).resolve().parent.name == "report":
        return Path(results).parent
    return _resolve_report_dir()


def _config_path(args: argparse.Namespace, root: Path) -> Path | None:
    """Return the configuration file to read, or None when --no-config is set.

    The order is --config, then VIP_CONFIG, then ``<root>/vip.toml``. A file
    that does not exist is an error: without it the scan misses every
    secret that only vip.toml holds.
    """
    if args.no_config:
        return None
    if args.config:
        path = Path(args.config)
    elif os.environ.get("VIP_CONFIG"):
        path = Path(os.environ["VIP_CONFIG"])
    else:
        path = root / "vip.toml"
    if not path.is_file():
        raise BundleError(
            f"no configuration file found at {path}. The secret scan needs it. "
            "Pass --config PATH. If you ran 'vip verify' with --connect-url and no "
            "vip.toml, pass --no-config: the scan then uses only the environment "
            "variables and the auth cache."
        )
    return path


def _load(path: Path) -> VIPConfig:
    """Load *path*. Turn a read error or a parse error into BundleError."""
    try:
        return load_config(path)
    # tomllib.TOMLDecodeError is a ValueError. A table of the wrong shape gives
    # AttributeError or TypeError in load_config.
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        raise BundleError(f"could not read {path}: {exc}") from exc


def _check_config_matches(config: VIPConfig, path: Path, results: bytes) -> None:
    """Refuse a configuration file that is not the one that ``vip verify`` used.

    results.json holds the deployment name and each product URL from the
    configuration of the run. If they differ, the scan would look for the
    wrong secrets.
    """
    data = json.loads(results)
    name = data.get("deployment_name")
    if isinstance(name, str) and name != config.deployment_name:
        raise BundleError(
            f"{path} does not match results.json: the deployment is "
            f"'{config.deployment_name}' in the configuration and '{name}' in "
            "results.json. Pass --config with the file that 'vip verify' used."
        )
    products = data.get("products")
    for product in _PRODUCTS:
        entry = products.get(product) if isinstance(products, dict) else None
        run_url = entry.get("url") if isinstance(entry, dict) else None
        url = config.product_config(product).url
        if run_url and url and run_url.rstrip("/") != url.rstrip("/"):
            raise BundleError(
                f"{path} does not match results.json: the {product} URL is "
                f"{strip_url_userinfo(url)} in the configuration and "
                f"{strip_url_userinfo(run_url)} in results.json. "
                "Pass --config with the file that 'vip verify' used."
            )


def _cache_secrets(root: Path) -> list[tuple[str, str]]:
    """Return the secrets in the auth cache files that ``vip verify`` run from *root* can write.

    The legacy files in *root* are read before ``auth_cache_path()`` is
    called, so that a cache location that moves the legacy files cannot hide
    them. ``auth_cache_path()`` depends on the working directory, so it is
    called from *root*.
    """
    legacy = root / AUTH_CACHE_FILENAME
    pairs = auth_cache_secrets(legacy) + auth_cache_secrets(legacy.with_suffix(".meta.json"))
    with contextlib.chdir(root):
        cache = auth_cache_path()
    if cache is not None and cache != legacy:
        pairs += auth_cache_secrets(cache) + auth_cache_secrets(cache.with_suffix(".meta.json"))
    return pairs


def _default_output(root: Path, results: bytes) -> Path:
    """Return ``<root>/vip-bundle-<deployment>-<UTC time>.zip``."""
    try:
        name = str(json.loads(results).get("deployment_name") or "")
    except (ValueError, AttributeError):
        name = ""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return root / ("vip-bundle-" + (f"{slug}-" if slug else "") + f"{stamp}.zip")


def _json_bytes(data: Any) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _hit_error(hits: list[tuple[str, str]], collected: Collected) -> BundleError:
    """Return the error for secret matches. Name each file and each source, never a value."""
    lines = ["refusing to write the bundle. The secret scan found a known credential:"]
    on_disk = made = False
    for name in sorted({name for name, _ in hits}):
        labels = ", ".join(sorted({label for member, label in hits if member == name}))
        if name in collected.sources:
            on_disk = True
            lines.append(f"  {collected.sources[name]}: {labels}")
        else:
            made = True
            lines.append(f"  {name} (made by vip bundle): {labels}")
    if on_disk:
        lines.append(
            "Edit each file to remove the value. Then run 'vip report' again and "
            "run 'vip bundle' again."
        )
    if made:
        lines.append(
            "A file that vip bundle makes holds the value, so a setting that is "
            "not secret has the same value. Change the credential."
        )
    lines.append(
        "If the value is not a real secret, pass --allow-match LABEL for each "
        "label. The manifest records each one."
    )
    return BundleError("\n".join(lines))


def run_bundle(args: argparse.Namespace) -> None:
    """Write a zip of the report output. Refuse when a member holds a known secret."""
    root = _invocation_root(args.results)
    report_dir = _report_dir(args.results)
    results_path = Path(args.results) if args.results else report_dir / "results.json"
    config_path = _config_path(args, root)
    # VIPConfig() still reads the VIP_* secret variables in its __post_init__ methods.
    config = _load(config_path) if config_path is not None else VIPConfig()

    collected = collect_members(results_path, report_dir)
    results = collected.members["report/results.json"]
    if config_path is not None:
        _check_config_matches(config, config_path, results)
    warnings = list(collected.warnings)
    if config_path is None:
        warnings.append(
            "--no-config is set, so the secret scan used only the environment "
            "variables and the auth cache. Look at the zip before you send it."
        )
    secrets = secret_values(config, _cache_secrets(root))
    warnings += [
        f"the value of {label} is shorter than 4 characters, so the secret scan "
        "cannot look for it. Look at the zip before you send it."
        for label in short_secret_labels(secrets)
    ]
    allowed = set(args.allow_match or [])
    unknown = sorted(allowed - {label for label, _ in secrets})
    if unknown:
        raise BundleError(
            f"--allow-match names no known credential: {', '.join(unknown)}. "
            "Use a label from the secret scan error."
        )

    output = Path(args.output) if args.output else _default_output(root, results)
    if output.exists() and not args.force:
        raise BundleError(
            f"{output} already exists. Pass --force to overwrite it, or pass --output PATH."
        )

    members = dict(collected.members)
    if config_path is not None:
        members["config-summary.json"] = _json_bytes(build_config_summary(config))
    members["version.txt"] = (_format_version_details() + "\n").encode("utf-8")

    # Scan every member before anything is written. The manifest is scanned
    # on its own after it is built, because it lists the allowed matches.
    hits = find_secret_hits(members, secrets)
    blocked = [hit for hit in hits if hit[1] not in allowed]
    if blocked:
        raise _hit_error(blocked, collected)
    allowed_hits = [hit for hit in hits if hit[1] in allowed]
    warnings += [
        f"the bundle holds the value of {label} in {name}, because --allow-match {label} is set."
        for name, label in allowed_hits
    ]

    members["manifest.json"] = _json_bytes(
        {
            "created_at": datetime.now(UTC).isoformat(),
            "vip_version": __version__,
            "members": sorted([*members, "manifest.json"]),
            "missing": sorted(collected.missing),
            "left_out": collected.left_out,
            "config_summary": config_path is not None,
            "secret_scan": "config" if config_path is not None else "no-config",
            "allowed_matches": [{"member": n, "label": label} for n, label in allowed_hits],
            "warnings": warnings,
        }
    )
    manifest_hits = [
        hit
        for hit in find_secret_hits({"manifest.json": members["manifest.json"]}, secrets)
        if hit[1] not in allowed
    ]
    if manifest_hits:
        raise _hit_error(manifest_hits, collected)

    for warning in warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    try:
        write_zip(output, members)
    except OSError as exc:
        raise BundleError(
            f"could not write {output}: {exc}. Pass --output PATH to write it somewhere else."
        ) from exc
    print(f"Bundle written: {output} ({len(members)} files)")
