"""``vip install`` and ``vip uninstall``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from vip.cli._common import _resolve_effective_ca_bundle
from vip.errors import InstallError

if TYPE_CHECKING:
    from vip.config import ProductConfig


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

        rc = execute_install_plan(
            plan,
            manifest=manifest,
            manifest_path=manifest_path,
            # Only Debian resolves a requested name to a different installed one.
            resolve_installed=installed_dpkg if info.family == "debian-family" else None,
        )
    except (PlaywrightInstallError, PackageQueryError) as exc:
        raise InstallError(str(exc)) from exc
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
        raise InstallError(str(exc)) from exc

    if manifest is None:
        raise InstallError(
            f"No {manifest_path.name} found. Nothing to uninstall, or vip was "
            "installed by a different mechanism."
        )

    if manifest.host != current_host() and not getattr(args, "force_host", False):
        raise InstallError(
            f"manifest host {manifest.host!r} does not match current host "
            f"{current_host()!r}. Pass --force-host to override."
        )

    # Load vip.toml (when present) regardless of whether --connect-url was
    # passed, so its [tls]/[proxy] settings apply to a --connect-url-only
    # invocation too -- otherwise a deployment behind a self-signed cert with
    # [tls] insecure = true in vip.toml has no route to that setting when the
    # Connect URL itself comes from the CLI. Loading stays silent when
    # vip.toml simply doesn't exist (mirrors _load_cleanup_config's guard);
    # test_run_uninstall_silent_when_vip_toml_missing pins the no-config case.
    # cfg carries the TLS settings (insecure/ca_bundle) for the
    # probe-and-fallback below whether the Connect URL came from vip.toml or
    # the CLI; with neither vip.toml present nor --insecure/--ca-bundle
    # passed, it probes with defaults (verify=True).
    from vip.config import ProductConfig

    connect_arg = getattr(args, "connect_url", None)

    cfg = None
    env = os.environ.get("VIP_CONFIG")
    config_path = Path(env) if env else Path("vip.toml")
    if config_path.exists():
        if sys.version_info >= (3, 11):
            import tomllib as _tomllib
        else:
            import tomli as _tomllib

        try:
            from vip.config import load_config

            cfg = load_config()
        except (_tomllib.TOMLDecodeError, ValueError) as exc:
            print(
                f"warning: failed to load vip.toml for chained cleanup: {exc}; "
                "continuing without vip.toml-derived settings",
                file=sys.stderr,
            )

    # A CLI --connect-url wins over vip.toml's [connect] url; wrapping it in
    # ProductConfig routes a scheme-less --connect-url through the same
    # _normalize_url every other entry point uses, so ConnectClient never
    # sees an unnormalized URL.
    if connect_arg:
        connect_pc: ProductConfig | None = ProductConfig(url=connect_arg)
    elif cfg and cfg.connect and cfg.connect.url:
        connect_pc = cfg.connect
    else:
        connect_pc = None

    # --insecure/--ca-bundle win over the corresponding vip.toml [tls] value,
    # same precedence _load_cleanup_config gives vip cleanup's equivalent flags.
    insecure = getattr(args, "insecure", False) or (cfg.insecure if cfg else False)
    ca_bundle = getattr(args, "ca_bundle", None) or (cfg.ca_bundle if cfg else None)
    ca_bundle = _resolve_effective_ca_bundle(insecure, ca_bundle)
    proxy = cfg.proxy if cfg else None
    yes = bool(getattr(args, "yes", False))

    # Resolve now, before the plan is built (and therefore before it's
    # printed) -- but only when --yes was passed. execute_uninstall_plan
    # prints format_uninstall_plan(plan) unconditionally, *before* its own
    # --yes gate; resolving lazily inside cleanup_callable (the previous
    # approach) meant the printed plan could announce
    # "run vip cleanup against https://host" and then actually clean up
    # against "http://host" once resolve_url_scheme downgraded it -- exactly
    # the kind of scheme mismatch this whole feature exists to prevent.
    # Gating on --yes preserves the dry-run guarantee: a plan preview must
    # never probe the network.
    if yes and connect_pc is not None:
        from vip.auth import resolve_url_scheme

        resolve_url_scheme(connect_pc, insecure=insecure, ca_bundle=ca_bundle, proxy=proxy)

    plan = build_uninstall_plan(
        manifest=manifest,
        connect_url=connect_pc.url if connect_pc else None,
    )

    cleanup_callable = None
    if connect_pc is not None:
        api_key = getattr(args, "api_key", None) or os.environ.get("VIP_CONNECT_API_KEY", "")

        def cleanup_callable(_url: str) -> None:
            from vip.auth import resolve_url_scheme
            from vip.clients.connect import ConnectClient

            # connect_pc.url was already resolved above -- this callable only
            # ever runs when execute_uninstall_plan actually executes
            # (--yes was passed), which is the same condition that already
            # triggered the resolve above, so the printed plan and the URL
            # used here are guaranteed to match. resolve_url_scheme is
            # idempotent (it resets url_scheme_inferred once resolved), so
            # calling it again here is a plain attribute read -- kept as a
            # belt-and-suspenders safety net rather than trusted by omission.
            resolved = resolve_url_scheme(
                connect_pc, insecure=insecure, ca_bundle=ca_bundle, proxy=proxy
            )
            with ConnectClient(
                resolved, api_key, insecure=insecure, ca_bundle=ca_bundle, proxy=proxy
            ) as client:
                client.cleanup_vip_content()

    rc = execute_uninstall_plan(
        plan,
        manifest_path=manifest_path,
        yes=yes,
        cleanup_callable=cleanup_callable,
    )
    sys.exit(rc)
