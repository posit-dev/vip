"""Tests for src/vip/install/plan.py."""

from __future__ import annotations

from pathlib import Path

from vip.install import plan as pl
from vip.install.manifest import (
    SCHEMA_VERSION,
    Manifest,
    PlaywrightItem,
    SystemPackageItem,
)
from vip.install.platform import PlatformInfo


def _empty_manifest(family: str = "rhel-family") -> Manifest:
    return Manifest(
        version=SCHEMA_VERSION,
        vip_version="0.0.0",
        created_at="",
        updated_at="",
        host="h",
        platform=family,
        platform_id="rhel",
        platform_version="10",
        items=[],
        pending_system_packages=[],
    )


def test_install_plan_rhel_all_missing(tmp_path: Path):
    info = PlatformInfo(family="rhel-family", id="rhel", version="10")
    plan = pl.build_install_plan(
        platform_info=info,
        manifest=None,
        rpm_installed=lambda names: set(),
        dpkg_installed=lambda names: set(),
        chromium_present=False,
        playwright_cache_dir=tmp_path / "cache",
        skip_system=False,
    )
    assert plan.platform == "rhel-family"
    assert plan.system_step is not None
    assert plan.system_step.manager == "dnf"
    assert "nss" in plan.system_step.packages
    assert plan.playwright_step is not None
    assert plan.is_empty() is False


def test_install_plan_rhel_all_present(tmp_path: Path):
    info = PlatformInfo(family="rhel-family", id="rhel", version="10")

    plan = pl.build_install_plan(
        platform_info=info,
        manifest=None,
        rpm_installed=lambda names: set(names),
        dpkg_installed=lambda names: set(),
        chromium_present=True,
        playwright_cache_dir=tmp_path / "cache",
        skip_system=False,
    )
    assert plan.system_step is None or plan.system_step.packages == ()
    assert plan.playwright_step is None
    assert plan.is_empty() is True


def test_install_plan_skip_system_omits_system_step(tmp_path: Path):
    info = PlatformInfo(family="rhel-family", id="rhel", version="10")
    plan = pl.build_install_plan(
        platform_info=info,
        manifest=None,
        rpm_installed=lambda names: set(),
        dpkg_installed=lambda names: set(),
        chromium_present=False,
        playwright_cache_dir=tmp_path / "cache",
        skip_system=True,
    )
    assert plan.system_step is None
    assert plan.playwright_step is not None


def test_install_plan_macos_skips_system(tmp_path: Path):
    info = PlatformInfo(family="macos")
    plan = pl.build_install_plan(
        platform_info=info,
        manifest=None,
        rpm_installed=lambda names: set(),
        dpkg_installed=lambda names: set(),
        chromium_present=False,
        playwright_cache_dir=tmp_path / "cache",
        skip_system=False,
    )
    assert plan.system_step is None
    assert plan.playwright_step is not None


def test_install_plan_unsupported_skips_system(tmp_path: Path):
    info = PlatformInfo(family="unsupported", id="void", version="rolling")
    plan = pl.build_install_plan(
        platform_info=info,
        manifest=None,
        rpm_installed=lambda names: set(),
        dpkg_installed=lambda names: set(),
        chromium_present=False,
        playwright_cache_dir=tmp_path / "cache",
        skip_system=False,
    )
    assert plan.system_step is None
    assert plan.unsupported_warning is not None


def test_install_plan_debian_uses_apt(tmp_path: Path):
    info = PlatformInfo(family="debian-family", id="ubuntu", version="24.04")
    plan = pl.build_install_plan(
        platform_info=info,
        manifest=None,
        rpm_installed=lambda names: set(),
        dpkg_installed=lambda names: set(),
        chromium_present=False,
        playwright_cache_dir=tmp_path / "cache",
        skip_system=False,
    )
    assert plan.system_step is not None
    assert plan.system_step.manager == "apt"
    assert "libnss3" in plan.system_step.packages


def test_install_plan_skips_already_installed_packages(tmp_path: Path):
    info = PlatformInfo(family="rhel-family", id="rhel", version="10")
    plan = pl.build_install_plan(
        platform_info=info,
        manifest=None,
        rpm_installed=lambda names: {"nss", "libdrm"},
        dpkg_installed=lambda names: set(),
        chromium_present=False,
        playwright_cache_dir=tmp_path / "cache",
        skip_system=False,
    )
    assert plan.system_step is not None
    assert "nss" not in plan.system_step.packages
    assert "libdrm" not in plan.system_step.packages
    assert "alsa-lib" in plan.system_step.packages


def test_install_plan_skips_packages_already_present_even_if_in_manifest(tmp_path: Path):
    info = PlatformInfo(family="rhel-family", id="rhel", version="10")
    m = _empty_manifest()
    m.items.append(SystemPackageItem(manager="dnf", name="nss", installed_at="t1"))
    plan = pl.build_install_plan(
        platform_info=info,
        manifest=m,
        rpm_installed=lambda names: {"nss"},
        dpkg_installed=lambda names: set(),
        chromium_present=False,
        playwright_cache_dir=tmp_path / "cache",
        skip_system=False,
    )
    # nss is present on the system — skip regardless of manifest membership.
    assert plan.system_step is not None
    assert "nss" not in plan.system_step.packages


def test_install_plan_replans_manifest_package_when_missing_from_system(tmp_path: Path):
    """If a manifest item is no longer installed on the system, plan re-installs it."""
    info = PlatformInfo(family="rhel-family", id="rhel", version="10")
    m = _empty_manifest()
    m.items.append(SystemPackageItem(manager="dnf", name="nss", installed_at="t1"))
    plan = pl.build_install_plan(
        platform_info=info,
        manifest=m,
        rpm_installed=lambda names: set(),  # nss is gone from system
        dpkg_installed=lambda names: set(),
        chromium_present=False,
        playwright_cache_dir=tmp_path / "cache",
        skip_system=False,
    )
    assert plan.system_step is not None
    assert "nss" in plan.system_step.packages


def test_install_plan_pending_packages_now_present_get_claimed(tmp_path: Path):
    info = PlatformInfo(family="rhel-family", id="rhel", version="10")
    m = _empty_manifest()
    m.pending_system_packages = ["nss", "libdrm"]
    plan = pl.build_install_plan(
        platform_info=info,
        manifest=m,
        rpm_installed=lambda names: {"nss"},  # libdrm still missing
        dpkg_installed=lambda names: set(),
        chromium_present=False,
        playwright_cache_dir=tmp_path / "cache",
        skip_system=False,
    )
    assert "nss" in plan.claim_pending
    assert "libdrm" not in plan.claim_pending
    # libdrm is still in the install step.
    assert plan.system_step is not None
    assert "libdrm" in plan.system_step.packages


def _full_manifest() -> Manifest:
    m = _empty_manifest()
    m.items = [
        SystemPackageItem(manager="dnf", name="nss", installed_at="t1"),
        SystemPackageItem(manager="dnf", name="libdrm", installed_at="t1"),
        PlaywrightItem(browser="chromium", cache_dir="/c", installed_at="t1"),
    ]
    return m


def test_uninstall_plan_default_scope():
    m = _full_manifest()
    plan = pl.build_uninstall_plan(
        manifest=m,
        venv=False,
        system=False,
        connect_url=None,
    )
    assert plan.delete_manifest is True
    assert plan.playwright_cache_dirs == ("/c",)
    assert plan.remove_venv is False
    assert plan.system_remove_command is None
    assert plan.chained_cleanup is None


def test_uninstall_plan_venv_flag_adds_venv():
    plan = pl.build_uninstall_plan(
        manifest=_full_manifest(), venv=True, system=False, connect_url=None
    )
    assert plan.remove_venv is True


def test_uninstall_plan_system_flag_emits_dnf_command():
    plan = pl.build_uninstall_plan(
        manifest=_full_manifest(), venv=False, system=True, connect_url=None
    )
    assert plan.system_remove_command is not None
    assert plan.system_remove_command.startswith("sudo dnf remove")
    assert "nss" in plan.system_remove_command
    assert "libdrm" in plan.system_remove_command


def test_uninstall_plan_system_flag_apt_when_manifest_apt():
    m = _full_manifest()
    m.items[0] = SystemPackageItem(manager="apt", name="libnss3", installed_at="t1")
    m.items[1] = SystemPackageItem(manager="apt", name="libdrm2", installed_at="t1")
    plan = pl.build_uninstall_plan(manifest=m, venv=False, system=True, connect_url=None)
    assert plan.system_remove_command is not None
    assert plan.system_remove_command.startswith("sudo apt remove --autoremove")
    assert "libnss3" in plan.system_remove_command


def test_uninstall_plan_system_flag_no_packages_no_command():
    m = _full_manifest()
    m.items = [PlaywrightItem(browser="chromium", cache_dir="/c", installed_at="t1")]
    plan = pl.build_uninstall_plan(manifest=m, venv=False, system=True, connect_url=None)
    assert plan.system_remove_command is None


def test_uninstall_plan_chains_cleanup_when_connect_url_present():
    plan = pl.build_uninstall_plan(
        manifest=_full_manifest(),
        venv=False,
        system=False,
        connect_url="https://connect.example.com",
    )
    assert plan.chained_cleanup == "https://connect.example.com"
