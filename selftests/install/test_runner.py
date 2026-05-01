"""Tests for src/vip/install/runner.py."""

from __future__ import annotations

from pathlib import Path

from vip.install import runner as rn
from vip.install.manifest import (
    SCHEMA_VERSION,
    Manifest,
    PlaywrightItem,
    SystemPackageItem,
)
from vip.install.plan import (
    InstallPlan,
    PlaywrightStep,
    SystemPackagesStep,
    UninstallPlan,
)


def _empty_manifest() -> Manifest:
    return Manifest(
        version=SCHEMA_VERSION,
        vip_version="0.0.0",
        created_at="t",
        updated_at="t",
        host="h",
        platform="rhel-family",
        platform_id="rhel",
        platform_version="10",
    )


def test_format_install_plan_empty():
    plan = InstallPlan(
        platform="rhel-family",
        platform_id="rhel",
        platform_version="10",
        system_step=None,
        playwright_step=None,
    )
    text = rn.format_install_plan(plan)
    assert "nothing to install" in text


def test_format_install_plan_with_packages_and_browser(tmp_path: Path):
    plan = InstallPlan(
        platform="rhel-family",
        platform_id="rhel",
        platform_version="10",
        system_step=SystemPackagesStep(manager="dnf", packages=("nss", "libdrm")),
        playwright_step=PlaywrightStep(browser="chromium", cache_dir=str(tmp_path)),
    )
    text = rn.format_install_plan(plan)
    assert "nss" in text and "libdrm" in text
    assert "chromium" in text
    assert "sudo dnf install" in text  # the user-facing command


def test_execute_install_plan_runs_playwright_and_writes_manifest(monkeypatch, tmp_path: Path):
    plan = InstallPlan(
        platform="rhel-family",
        platform_id="rhel",
        platform_version="10",
        system_step=SystemPackagesStep(manager="dnf", packages=()),
        playwright_step=PlaywrightStep(browser="chromium", cache_dir=str(tmp_path / "cache")),
    )
    invoked = []
    monkeypatch.setattr(rn, "install_chromium", lambda: invoked.append("pw"))

    manifest_path = tmp_path / ".vip-install.json"
    manifest = _empty_manifest()
    rn.execute_install_plan(plan, manifest=manifest, manifest_path=manifest_path)

    assert invoked == ["pw"]
    from vip.install.manifest import load

    saved = load(manifest_path)
    assert saved is not None
    assert any(isinstance(i, PlaywrightItem) for i in saved.items)


def test_execute_install_plan_records_pending_when_root_required(monkeypatch, tmp_path: Path):
    """When system_step has packages and the user isn't root, runner returns code 2
    after writing pending packages to the manifest."""
    plan = InstallPlan(
        platform="rhel-family",
        platform_id="rhel",
        platform_version="10",
        system_step=SystemPackagesStep(manager="dnf", packages=("nss", "libdrm")),
        playwright_step=None,
    )
    monkeypatch.setattr(rn, "is_root", lambda: False)
    manifest_path = tmp_path / ".vip-install.json"
    manifest = _empty_manifest()

    rc = rn.execute_install_plan(plan, manifest=manifest, manifest_path=manifest_path)

    assert rc == 2
    from vip.install.manifest import load

    saved = load(manifest_path)
    assert set(saved.pending_system_packages) == {"nss", "libdrm"}


def test_execute_install_plan_claims_pending(monkeypatch, tmp_path: Path):
    plan = InstallPlan(
        platform="rhel-family",
        platform_id="rhel",
        platform_version="10",
        system_step=SystemPackagesStep(manager="dnf", packages=()),
        playwright_step=None,
        claim_pending=("nss",),
    )
    manifest = _empty_manifest()
    manifest.pending_system_packages = ["nss", "libdrm"]
    manifest_path = tmp_path / ".vip-install.json"

    rn.execute_install_plan(plan, manifest=manifest, manifest_path=manifest_path)

    from vip.install.manifest import load

    saved = load(manifest_path)
    assert "nss" in [i.name for i in saved.items if isinstance(i, SystemPackageItem)]
    assert "nss" not in saved.pending_system_packages
    assert "libdrm" in saved.pending_system_packages


def test_format_install_plan_unsupported_warning_visible_when_otherwise_empty():
    """Unsupported-platform warning must show even when no work is queued."""
    plan = InstallPlan(
        platform="unsupported",
        platform_id="void",
        platform_version="rolling",
        system_step=None,
        playwright_step=None,
        unsupported_warning="Platform void is unsupported; skipping system step.",
    )
    text = rn.format_install_plan(plan)
    assert "nothing to install" not in text
    assert "warning" in text.lower()
    assert "void" in text  # platform id propagates
    assert "unsupported" in text  # warning text shows


def test_format_uninstall_plan_default():
    plan = UninstallPlan(
        delete_manifest=True,
        playwright_cache_dirs=("/c",),
        system_remove_commands=(),
        chained_cleanup=None,
    )
    text = rn.format_uninstall_plan(plan)
    assert "/c" in text
    assert ".venv" not in text


def test_format_uninstall_plan_with_all_scopes():
    plan = UninstallPlan(
        delete_manifest=True,
        playwright_cache_dirs=("/c",),
        system_remove_commands=("sudo dnf remove nss libdrm",),
        chained_cleanup="https://connect.example.com",
    )
    text = rn.format_uninstall_plan(plan)
    assert "sudo dnf remove" in text
    assert "connect.example.com" in text


def test_execute_uninstall_plan_dry_run(monkeypatch, tmp_path: Path):
    """yes=False prints plan, makes no changes."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    manifest_path = tmp_path / ".vip-install.json"
    manifest_path.write_text("{}")

    plan = UninstallPlan(
        delete_manifest=True,
        playwright_cache_dirs=(str(cache_dir),),
        system_remove_commands=(),
        chained_cleanup=None,
    )
    rc = rn.execute_uninstall_plan(
        plan,
        manifest_path=manifest_path,
        yes=False,
        cleanup_callable=None,
    )
    assert rc == 0
    assert cache_dir.exists()
    assert manifest_path.exists()


def test_execute_uninstall_plan_with_yes_removes_things(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    manifest_path = tmp_path / ".vip-install.json"
    manifest_path.write_text("{}")

    plan = UninstallPlan(
        delete_manifest=True,
        playwright_cache_dirs=(str(cache_dir),),
        system_remove_commands=(),
        chained_cleanup=None,
    )
    rc = rn.execute_uninstall_plan(
        plan,
        manifest_path=manifest_path,
        yes=True,
        cleanup_callable=None,
    )
    assert rc == 0
    assert not cache_dir.exists()
    assert not manifest_path.exists()


def test_execute_uninstall_plan_chained_cleanup_failure_warns(tmp_path: Path, capsys):
    manifest_path = tmp_path / ".vip-install.json"
    manifest_path.write_text("{}")

    def boom(connect_url: str) -> None:
        raise RuntimeError("connect down")

    plan = UninstallPlan(
        delete_manifest=True,
        playwright_cache_dirs=(),
        system_remove_commands=(),
        chained_cleanup="https://connect.example.com",
    )
    rc = rn.execute_uninstall_plan(
        plan,
        manifest_path=manifest_path,
        yes=True,
        cleanup_callable=boom,
    )
    assert rc == 0
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "warn" in out.lower() or "WARN" in out
    # Status was failed, not skipped — final summary mentions content cleanup.
    assert "content cleanup: failed" in captured.out


def test_execute_uninstall_plan_skipped_status_omits_content_cleanup_note(tmp_path, capsys):
    """No chained cleanup configured: don't tack on a confusing '(content cleanup: skipped)'."""
    manifest_path = tmp_path / ".vip-install.json"
    manifest_path.write_text("{}")

    plan = UninstallPlan(
        delete_manifest=True,
        playwright_cache_dirs=(),
        system_remove_commands=(),
        chained_cleanup=None,
    )
    rn.execute_uninstall_plan(plan, manifest_path=manifest_path, yes=True, cleanup_callable=None)
    captured = capsys.readouterr()
    assert "vip uninstall: complete" in captured.out
    assert "content cleanup" not in captured.out


def test_execute_uninstall_plan_yes_prints_uv_uninstall_hint(tmp_path, capsys):
    """After --yes, remind the user how to remove vip itself."""
    manifest_path = tmp_path / ".vip-install.json"
    manifest_path.write_text("{}")

    plan = UninstallPlan(
        delete_manifest=True,
        playwright_cache_dirs=(),
        system_remove_commands=(),
        chained_cleanup=None,
    )
    rn.execute_uninstall_plan(plan, manifest_path=manifest_path, yes=True, cleanup_callable=None)
    captured = capsys.readouterr()
    assert "uv tool uninstall posit-vip" in captured.out
    assert "uv pip uninstall posit-vip" in captured.out


def test_execute_install_plan_root_install_clears_pending(monkeypatch, tmp_path):
    """Root-install path must drop the just-installed names from pending_system_packages."""
    plan = InstallPlan(
        platform="rhel-family",
        platform_id="rhel",
        platform_version="10",
        system_step=SystemPackagesStep(manager="dnf", packages=("nss", "libdrm")),
        playwright_step=None,
    )
    monkeypatch.setattr(rn, "is_root", lambda: True)
    # Stub out the actual dnf call.
    monkeypatch.setattr(rn, "_install_system_packages", lambda manager, packages: None)
    manifest = _empty_manifest()
    manifest.pending_system_packages = ["nss", "libdrm", "alsa-lib"]
    manifest_path = tmp_path / ".vip-install.json"

    rc = rn.execute_install_plan(plan, manifest=manifest, manifest_path=manifest_path)
    assert rc == 0

    from vip.install.manifest import load

    saved = load(manifest_path)
    assert "nss" not in saved.pending_system_packages
    assert "libdrm" not in saved.pending_system_packages
    assert "alsa-lib" in saved.pending_system_packages  # not part of system_step
    # Each installed name should appear exactly once in items.
    names = [i.name for i in saved.items if isinstance(i, SystemPackageItem)]
    assert names.count("nss") == 1
    assert names.count("libdrm") == 1


def test_execute_uninstall_plan_dry_run_does_not_print_uv_uninstall_hint(tmp_path, capsys):
    """The reminder should only appear after actual --yes execution."""
    manifest_path = tmp_path / ".vip-install.json"
    manifest_path.write_text("{}")

    plan = UninstallPlan(
        delete_manifest=True,
        playwright_cache_dirs=(),
        system_remove_commands=(),
        chained_cleanup=None,
    )
    rn.execute_uninstall_plan(plan, manifest_path=manifest_path, yes=False, cleanup_callable=None)
    captured = capsys.readouterr()
    assert "uv pip uninstall posit-vip" not in captured.out
