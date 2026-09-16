"""Pure functions to build install/uninstall plans from inputs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from vip.install import platform as plat
from vip.install.manifest import Manifest, PlaywrightItem, SystemPackageItem


@dataclass(frozen=True)
class SystemPackagesStep:
    """The system packages ``vip install`` still needs to install for one package manager."""

    manager: str  # "dnf" | "apt" | "zypper"
    packages: tuple[str, ...]


@dataclass(frozen=True)
class PlaywrightStep:
    """The Playwright browser ``vip install`` still needs to download, and where to."""

    browser: str  # "chromium"
    cache_dir: str


@dataclass(frozen=True)
class InstallPlan:
    """What ``vip install`` needs to do on this host, computed without doing any of it.

    ``system_step``/``playwright_step`` are ``None`` when nothing is needed for that
    part. ``claim_pending`` lists manifest packages that were pending (needed a manual
    ``sudo`` install) and are now present, to be recorded as installed rather than
    requested again. ``unsupported_warning`` is set only on an unsupported platform,
    where ``system_step`` is left ``None`` instead of being computed.
    """

    platform: str
    platform_id: str | None
    platform_version: str | None
    system_step: SystemPackagesStep | None
    playwright_step: PlaywrightStep | None
    # (pending_name, concrete_name) pairs -- see build_install_plan's comment.
    claim_pending: tuple[tuple[str, str], ...] = ()
    unsupported_warning: str | None = None

    def is_empty(self) -> bool:
        """Return True if this plan has no packages to install and nothing to claim."""
        if self.system_step and self.system_step.packages:
            return False
        if self.playwright_step:
            return False
        return not self.claim_pending


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
    dpkg_installed: Callable[[tuple[str, ...]], dict[str, str]],
    chromium_present: bool,
    playwright_cache_dir: Path,
    skip_system: bool,
) -> InstallPlan:
    """Decide what ``vip install`` still needs to do, without doing any of it.

    Pure: ``rpm_installed``/``dpkg_installed`` are injected callables (not called
    directly against the system) and ``chromium_present`` is a precomputed bool,
    so this function performs no I/O itself and is safe to call from tests.

    Branches by ``platform_info.family``:
    - ``rhel-family``/``debian-family``/``suse-family``: diffs the canonical package
      list for that family against what's already present, and sets
      ``system_step`` to only the missing packages (manager ``dnf``/``apt``/``zypper``
      respectively). Any ``manifest`` package still marked pending that is now
      present is moved into ``claim_pending`` instead of being requested again;
      for ``debian-family`` this reconciliation also maps a manifest entry
      recorded under a legacy package name (e.g. ``libasound2``) onto its
      current replacement (``libasound2t64``) before checking presence.
    - ``macos``: ``system_step`` is left ``None`` (no system-package step exists).
    - ``unsupported``: ``system_step`` is left ``None`` and ``unsupported_warning`` is
      set to a message naming the platform.

    If ``skip_system`` is true, the platform branch above is skipped entirely
    and ``system_step``/``claim_pending``/``unsupported_warning`` stay at their
    defaults, regardless of platform family.

    ``playwright_step`` is set whenever ``chromium_present`` is false, independent
    of ``skip_system`` and platform family.
    """
    family = platform_info.family
    system_step: SystemPackagesStep | None = None
    unsupported_warning: str | None = None
    # Each entry pairs the manifest's pending name with the concrete package
    # name to record as claimed. They're almost always identical; they differ
    # when the pending name is an alias resolved via dpkg Provides (or a
    # legacy renamed package), so the manifest ends up naming what is
    # actually installed and removable, not the alias that was asked for.
    claim_pending: tuple[tuple[str, str], ...] = ()

    pending = manifest.pending_packages_set() if manifest else set()

    if not skip_system:
        if family == "rhel-family":
            present = rpm_installed(plat.RHEL_PACKAGES)
            claim_pending = tuple(sorted((n, n) for n in (pending & present)))
            missing = tuple(p for p in plat.RHEL_PACKAGES if p not in present)
            system_step = SystemPackagesStep(manager="dnf", packages=missing)
        elif family == "debian-family":
            packages = plat.debian_packages(platform_info)
            resolved = dpkg_installed(packages)
            present = set(resolved)
            # Normalize legacy pending names: if the manifest recorded
            # "libasound2" but we now install "libasound2t64", treat the old
            # name as claimable when the new name is present.
            normalized_pending = _normalize_pending_debian(pending, packages)
            claim_pending = tuple(
                sorted((name, resolved[name]) for name in (normalized_pending & present))
            )
            missing = tuple(p for p in packages if p not in present)
            system_step = SystemPackagesStep(manager="apt", packages=missing)
        elif family == "suse-family":
            present = rpm_installed(plat.SUSE_PACKAGES)
            claim_pending = tuple(sorted((n, n) for n in (pending & present)))
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
    """What ``vip uninstall`` needs to do, derived from a ``Manifest``.

    ``delete_manifest`` is always ``True``. ``system_remove_commands`` covers only the
    ``dnf``/``apt``/``zypper`` managers; a manifest item with any other manager is
    silently omitted. ``chained_cleanup`` is the Connect URL to sweep VIP content
    against, or ``None`` if uninstall should not chain into a Connect cleanup.
    """

    delete_manifest: bool
    playwright_cache_dirs: tuple[str, ...]
    system_remove_commands: tuple[str, ...]
    chained_cleanup: str | None  # connect URL to clean up against, or None


def build_uninstall_plan(
    *,
    manifest: Manifest,
    connect_url: str | None,
) -> UninstallPlan:
    """Turn a ``Manifest`` into a plan the runner or a dry-run print can act on.

    Pure and total: reads only ``manifest`` and ``connect_url``, performs no I/O,
    and always succeeds. ``delete_manifest`` is unconditionally ``True`` since a
    manifest always names itself for deletion once its contents are read.
    ``playwright_cache_dirs`` and each manager's package list are deduplicated
    (via ``set``) and sorted before being turned into commands, so plan output
    is stable across repeated calls with the same manifest. A manager not in
    ``{"dnf", "apt", "zypper"}`` is silently dropped from
    ``system_remove_commands`` with no warning and no record kept anywhere —
    ``UninstallPlan`` has no field for omitted packages, and the manifest that
    named them is deleted unconditionally once uninstall runs, so nothing
    about them survives past this call.
    ``chained_cleanup`` is ``connect_url`` passed through unchanged and
    unvalidated; the caller decides what it means to act on it.
    """
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
