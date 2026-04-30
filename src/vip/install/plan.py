"""Pure functions to build install/uninstall plans from inputs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from vip.install import platform as plat
from vip.install.manifest import Manifest, PlaywrightItem, SystemPackageItem


@dataclass(frozen=True)
class SystemPackagesStep:
    manager: str  # "dnf" | "apt"
    packages: tuple[str, ...]


@dataclass(frozen=True)
class PlaywrightStep:
    browser: str  # "chromium"
    cache_dir: str


@dataclass(frozen=True)
class InstallPlan:
    platform: str
    platform_id: str | None
    platform_version: str | None
    system_step: SystemPackagesStep | None
    playwright_step: PlaywrightStep | None
    claim_pending: tuple[str, ...] = ()
    unsupported_warning: str | None = None

    def is_empty(self) -> bool:
        if self.system_step and self.system_step.packages:
            return False
        if self.playwright_step:
            return False
        if self.claim_pending:
            return False
        return True


def build_install_plan(
    *,
    platform_info: plat.PlatformInfo,
    manifest: Manifest | None,
    rpm_installed: Callable[[tuple[str, ...]], set[str]],
    dpkg_installed: Callable[[tuple[str, ...]], set[str]],
    chromium_present: bool,
    playwright_cache_dir: Path,
    skip_system: bool,
) -> InstallPlan:
    family = platform_info.family
    system_step: SystemPackagesStep | None = None
    unsupported_warning: str | None = None
    claim_pending: tuple[str, ...] = ()

    pending = manifest.pending_packages_set() if manifest else set()

    if not skip_system:
        if family == "rhel-family":
            present = rpm_installed(plat.RHEL_PACKAGES)
            claim_pending = tuple(sorted(pending & present))
            missing = tuple(p for p in plat.RHEL_PACKAGES if p not in present)
            system_step = SystemPackagesStep(manager="dnf", packages=missing)
        elif family == "debian-family":
            present = dpkg_installed(plat.DEBIAN_PACKAGES)
            claim_pending = tuple(sorted(pending & present))
            missing = tuple(p for p in plat.DEBIAN_PACKAGES if p not in present)
            system_step = SystemPackagesStep(manager="apt", packages=missing)
        elif family == "macos":
            system_step = None
        elif family == "unsupported":
            unsupported_warning = (
                f"Platform {platform_info.id or 'unknown'} is unsupported; "
                "skipping system-package step. File an issue at "
                "https://github.com/posit-dev/vip/issues if you'd like it added."
            )

    playwright_step: PlaywrightStep | None = None
    if not chromium_present:
        playwright_step = PlaywrightStep(browser="chromium", cache_dir=str(playwright_cache_dir))

    return InstallPlan(
        platform=family,
        platform_id=platform_info.id,
        platform_version=platform_info.version,
        system_step=system_step,
        playwright_step=playwright_step,
        claim_pending=claim_pending,
        unsupported_warning=unsupported_warning,
    )


@dataclass(frozen=True)
class UninstallPlan:
    delete_manifest: bool
    playwright_cache_dirs: tuple[str, ...]
    remove_venv: bool
    system_remove_command: str | None
    chained_cleanup: str | None  # connect URL to clean up against, or None
    system_packages_by_manager: dict[str, tuple[str, ...]] = field(default_factory=dict)


def build_uninstall_plan(
    *,
    manifest: Manifest,
    venv: bool,
    system: bool,
    connect_url: str | None,
) -> UninstallPlan:
    cache_dirs = tuple(
        sorted({i.cache_dir for i in manifest.items if isinstance(i, PlaywrightItem)})
    )

    by_manager: dict[str, list[str]] = {}
    for it in manifest.items:
        if isinstance(it, SystemPackageItem):
            by_manager.setdefault(it.manager, []).append(it.name)
    by_manager_tuples = {m: tuple(sorted(set(names))) for m, names in by_manager.items()}

    system_command: str | None = None
    if system and by_manager_tuples:
        # Prefer the manager with the most packages; mixed-manager manifests are unusual
        # (a host has only one of dnf or apt) but we handle the case for completeness.
        primary = max(by_manager_tuples.items(), key=lambda kv: len(kv[1]))
        manager, names = primary
        if manager == "dnf":
            system_command = "sudo dnf remove " + " ".join(names)
        elif manager == "apt":
            system_command = "sudo apt remove --autoremove " + " ".join(names)

    return UninstallPlan(
        delete_manifest=True,
        playwright_cache_dirs=cache_dirs,
        remove_venv=venv,
        system_remove_command=system_command,
        chained_cleanup=connect_url,
        system_packages_by_manager=by_manager_tuples,
    )
