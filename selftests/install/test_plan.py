"""Tests for src/vip/install/plan.py."""

from __future__ import annotations

from pathlib import Path

from vip.install import plan as pl
from vip.install.manifest import (
    SCHEMA_VERSION,
    Manifest,
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


def test_install_plan_with_existing_manifest_carries_state(tmp_path: Path):
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
    # nss is present and already in manifest — not in plan.
    assert plan.system_step is not None
    assert "nss" not in plan.system_step.packages


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
