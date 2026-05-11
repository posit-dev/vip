"""Pure functions to build install/uninstall plans from inputs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from vip.install import platform as plat
from vip.install.manifest import Manifest, PlaywrightItem, SystemPackageItem


@dataclass(frozen=True)
class SystemPackagesStep:
    manager: str  # "dnf" | "apt" | "zypper"
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


# Maps old Debian package names to their t64 replacements.
# Used to reconcile manifest entries recorded under the pre-24.04 name.
_DEBIAN_RENAME_MAP: dict[str, str] = {"libasound2": "libasound2t64"}


def _normalize_pending_debian(pending: set[str], current_packages: tuple[str, ...]) -> set[str]:
    """Map legacy pending names to the current package list.

    If the manifest recorded "libasound2" but we now install "libasound2t64",
    rewrite the pending entry so ``claim_pending`` can match.
    """
    current = set(current_packages)
    out: set[str] = set()
    for name in pending:
        new_name = _DEBIAN_RENAME_MAP.get(name)
        if new_name and new_name in current and name not in current:
            out.add(new_name)
        else:
            out.add(name)
    return out


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
            packages = plat.debian_packages(platform_info)
            present = dpkg_installed(packages)
            # Normalize legacy pending names: if the manifest recorded
            # "libasound2" but we now install "libasound2t64", treat the old
            # name as claimable when the new name is present.
            normalized_pending = _normalize_pending_debian(pending, packages)
            claim_pending = tuple(sorted(normalized_pending & present))
            missing = tuple(p for p in packages if p not in present)
            system_step = SystemPackagesStep(manager="apt", packages=missing)
        elif family == "suse-family":
            present = rpm_installed(plat.SUSE_PACKAGES)
            claim_pending = tuple(sorted(pending & present))
            missing = tuple(p for p in plat.SUSE_PACKAGES if p not in present)
            system_step = SystemPackagesStep(manager="zypper", packages=missing)
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
    system_remove_commands: tuple[str, ...]
    chained_cleanup: str | None  # connect URL to clean up against, or None


def build_uninstall_plan(
    *,
    manifest: Manifest,
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

    commands: list[str] = []
    for manager, names in sorted(by_manager_tuples.items()):
        if not names:
            continue
        if manager == "dnf":
            commands.append("sudo dnf remove " + " ".join(names))
        elif manager == "apt":
            commands.append("sudo apt remove --autoremove " + " ".join(names))
        elif manager == "zypper":
            commands.append("sudo zypper remove " + " ".join(names))
        # Unknown manager: skip (we don't know how to remove)

    return UninstallPlan(
        delete_manifest=True,
        playwright_cache_dirs=cache_dirs,
        system_remove_commands=tuple(commands),
        chained_cleanup=connect_url,
    )
