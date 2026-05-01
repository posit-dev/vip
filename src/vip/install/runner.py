"""Execute or pretty-print install/uninstall plans."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from vip.install.manifest import (
    Manifest,
    PlaywrightItem,
    SystemPackageItem,
    save,
)
from vip.install.plan import (
    InstallPlan,
    UninstallPlan,
)
from vip.install.playwright import install_chromium


def is_root() -> bool:
    """True if the current process can install system packages without sudo."""
    return os.geteuid() == 0 if hasattr(os, "geteuid") else False


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_install_plan(plan: InstallPlan) -> str:
    if plan.is_empty() and not plan.unsupported_warning:
        return "vip install: already up to date.\n"
    lines = [
        f"vip install plan ({plan.platform_id or plan.platform} {plan.platform_version or ''}):"
    ]
    if plan.unsupported_warning:
        lines.append(f"  warning: {plan.unsupported_warning}")
    if plan.is_empty():
        lines.append("  (nothing else to do)")
    if plan.system_step and plan.system_step.packages:
        manager = plan.system_step.manager
        cmd = "sudo dnf install -y" if manager == "dnf" else "sudo apt install -y"
        lines.append("  system packages to install (run yourself if not root):")
        lines.append(f"    {cmd} {' '.join(plan.system_step.packages)}")
    if plan.claim_pending:
        lines.append(
            "  pending packages now installed, will be claimed: " + " ".join(plan.claim_pending)
        )
    if plan.playwright_step:
        lines.append(
            f"  playwright: install {plan.playwright_step.browser} "
            f"into {plan.playwright_step.cache_dir}"
        )
    return "\n".join(lines) + "\n"


def execute_install_plan(
    plan: InstallPlan,
    *,
    manifest: Manifest,
    manifest_path: Path,
) -> int:
    """Execute an install plan. Returns CLI exit code (0=ok, 2=needs sudo)."""
    print(format_install_plan(plan), end="")

    system_step = plan.system_step
    needs_root = bool(system_step and system_step.packages)
    now = _now()

    # Always claim pending packages that are now present.
    if plan.claim_pending:
        manifest.claim_pending(
            plan.claim_pending, installed_at=now, manager=_manager_for(plan.platform)
        )

    if needs_root and system_step is not None and not is_root():
        manifest.add_pending_packages(system_step.packages)
        manifest.updated_at = now
        save(manifest, manifest_path)
        cmd = "sudo dnf install -y" if system_step.manager == "dnf" else "sudo apt install -y"
        print(f"\nNot running as root. Please run:\n  {cmd} {' '.join(system_step.packages)}")
        print("Then re-run `vip install`.")
        return 2

    # Run system step ourselves if root.
    if needs_root and system_step is not None and is_root():
        _install_system_packages(system_step.manager, system_step.packages)
        for name in system_step.packages:
            manifest.items.append(
                SystemPackageItem(manager=system_step.manager, name=name, installed_at=now)
            )
        manifest.pending_system_packages = [
            p for p in manifest.pending_system_packages if p not in set(system_step.packages)
        ]

    # Run Playwright step.
    if plan.playwright_step:
        install_chromium()
        manifest.items.append(
            PlaywrightItem(
                browser=plan.playwright_step.browser,
                cache_dir=plan.playwright_step.cache_dir,
                installed_at=now,
            )
        )

    manifest.updated_at = now
    save(manifest, manifest_path)
    return 0


def _manager_for(platform_family: str) -> str:
    return "dnf" if platform_family == "rhel-family" else "apt"


def _install_system_packages(manager: str, packages: tuple[str, ...]) -> None:
    if not packages:
        return
    if manager == "dnf":
        subprocess.run(["dnf", "install", "-y", *packages], check=True)
    elif manager == "apt":
        subprocess.run(["apt", "install", "-y", *packages], check=True)
    else:
        raise ValueError(f"Unknown manager {manager!r}")


def format_uninstall_plan(plan: UninstallPlan) -> str:
    lines = ["vip uninstall plan:"]
    if plan.chained_cleanup:
        lines.append(f"  run vip cleanup against {plan.chained_cleanup}")
    if plan.playwright_cache_dirs:
        for d in plan.playwright_cache_dirs:
            lines.append(f"  remove playwright cache: {d}")
    if plan.delete_manifest:
        lines.append("  delete .vip-install.json")
    if plan.system_remove_commands:
        lines.append("  system packages to remove (run yourself):")
        for cmd in plan.system_remove_commands:
            lines.append(f"    {cmd}")
    return "\n".join(lines) + "\n"


def execute_uninstall_plan(
    plan: UninstallPlan,
    *,
    manifest_path: Path,
    yes: bool,
    cleanup_callable: Callable[[str], None] | None,
) -> int:
    print(format_uninstall_plan(plan), end="")
    if not yes:
        print("\nDry run only. Pass --yes to execute.")
        return 0

    cleanup_status = "skipped"
    if plan.chained_cleanup and cleanup_callable is not None:
        try:
            cleanup_callable(plan.chained_cleanup)
            cleanup_status = "ok"
        except Exception as exc:  # noqa: BLE001
            print(f"warning: chained vip cleanup failed: {exc}")
            cleanup_status = "failed"

    for cache_dir in plan.playwright_cache_dirs:
        p = Path(cache_dir)
        if p.exists():
            shutil.rmtree(p)

    if plan.delete_manifest and manifest_path.exists():
        manifest_path.unlink()

    if plan.system_remove_commands:
        print("\nRun the following yourself to remove system packages:")
        for cmd in plan.system_remove_commands:
            print(f"  {cmd}")

    if cleanup_status == "skipped":
        print("\nvip uninstall: complete")
    else:
        print(f"\nvip uninstall: complete (content cleanup: {cleanup_status})")

    print(
        "\nTo also remove vip itself, run one of:\n"
        "  uv tool uninstall posit-vip   # if installed via `uv tool install`\n"
        "  uv pip uninstall posit-vip    # if installed via `uv pip install`"
    )
    return 0
