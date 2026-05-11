"""Tests for src/vip/install/platform.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from vip.install import platform as plat


@pytest.fixture()
def fake_os_release(tmp_path: Path, monkeypatch):
    def _write(content: str) -> Path:
        p = tmp_path / "os-release"
        p.write_text(content)
        monkeypatch.setattr(plat, "_OS_RELEASE_PATH", p)
        return p

    return _write


def test_detect_macos(monkeypatch):
    monkeypatch.setattr(plat.sys, "platform", "darwin")
    info = plat.detect()
    assert info.family == "macos"
    assert info.id is None
    assert info.version is None


def test_detect_windows(monkeypatch):
    monkeypatch.setattr(plat.sys, "platform", "win32")
    info = plat.detect()
    assert info.family == "unsupported"


def test_detect_rhel10(monkeypatch, fake_os_release):
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release('ID=rhel\nVERSION_ID="10"\n')
    info = plat.detect()
    assert info.family == "rhel-family"
    assert info.id == "rhel"
    assert info.version == "10"


def test_detect_rhel9(monkeypatch, fake_os_release):
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release('ID=rhel\nVERSION_ID="9.4"\n')
    info = plat.detect()
    assert info.family == "rhel-family"


def test_detect_rocky(monkeypatch, fake_os_release):
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release('ID=rocky\nVERSION_ID="9.4"\nID_LIKE="rhel centos fedora"\n')
    info = plat.detect()
    assert info.family == "rhel-family"


def test_detect_oracle_via_id_like(monkeypatch, fake_os_release):
    """Oracle Linux's ID is 'ol'; routing depends on ID_LIKE=fedora."""
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release('ID="ol"\nVERSION_ID="9.4"\nID_LIKE="fedora"\n')
    info = plat.detect()
    assert info.family == "rhel-family"


def test_detect_ubuntu(monkeypatch, fake_os_release):
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release('ID=ubuntu\nVERSION_ID="24.04"\n')
    info = plat.detect()
    assert info.family == "debian-family"
    assert info.id == "ubuntu"
    assert info.version == "24.04"


def test_detect_debian(monkeypatch, fake_os_release):
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release('ID=debian\nVERSION_ID="12"\n')
    info = plat.detect()
    assert info.family == "debian-family"


def test_detect_popos_via_id_like(monkeypatch, fake_os_release):
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release('ID=pop\nID_LIKE="ubuntu debian"\nVERSION_ID="22.04"\n')
    info = plat.detect()
    assert info.family == "debian-family"


def test_detect_opensuse_leap(monkeypatch, fake_os_release):
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release('ID="opensuse-leap"\nVERSION_ID="15.6"\nID_LIKE="suse opensuse"\n')
    info = plat.detect()
    assert info.family == "suse-family"
    assert info.id == "opensuse-leap"
    assert info.version == "15.6"


def test_detect_opensuse_tumbleweed(monkeypatch, fake_os_release):
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release('ID="opensuse-tumbleweed"\nVERSION_ID="20260101"\nID_LIKE="opensuse suse"\n')
    info = plat.detect()
    assert info.family == "suse-family"


def test_detect_sles(monkeypatch, fake_os_release):
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release('ID="sles"\nVERSION_ID="15.5"\nID_LIKE="suse"\n')
    info = plat.detect()
    assert info.family == "suse-family"


def test_detect_suse_via_id_like_only(monkeypatch, fake_os_release):
    """A SUSE-derivative whose ID is something else should still route to suse-family."""
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release('ID="microos"\nID_LIKE="suse opensuse"\nVERSION_ID="6"\n')
    info = plat.detect()
    assert info.family == "suse-family"


def test_detect_unknown_linux(monkeypatch, fake_os_release):
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release('ID=void\nVERSION_ID="rolling"\n')
    info = plat.detect()
    assert info.family == "unsupported"


def test_detect_handles_malformed_os_release_line(monkeypatch, fake_os_release):
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release('ID=rhel\nPRETTY_NAME="unterminated\n')
    info = plat.detect()
    assert info.family == "rhel-family"


def test_detect_missing_os_release(monkeypatch, tmp_path):
    monkeypatch.setattr(plat.sys, "platform", "linux")
    monkeypatch.setattr(plat, "_OS_RELEASE_PATH", tmp_path / "does-not-exist")
    info = plat.detect()
    assert info.family == "unsupported"


def test_rhel_packages_is_tuple_of_strings():
    assert isinstance(plat.RHEL_PACKAGES, tuple)
    assert all(isinstance(p, str) and p for p in plat.RHEL_PACKAGES)
    # Spot check on the canonical Chromium runtime libs
    assert "nss" in plat.RHEL_PACKAGES
    assert "libdrm" in plat.RHEL_PACKAGES


def test_debian_packages_is_tuple_of_strings():
    assert isinstance(plat.DEBIAN_PACKAGES, tuple)
    assert all(isinstance(p, str) and p for p in plat.DEBIAN_PACKAGES)
    # Spot check from Playwright nativeDeps.ts
    assert "libnss3" in plat.DEBIAN_PACKAGES


def test_debian_packages_ubuntu_2404_uses_libasound2t64():
    info = plat.PlatformInfo(family="debian-family", id="ubuntu", version="24.04")
    pkgs = plat.debian_packages(info)
    assert "libasound2t64" in pkgs
    assert "libasound2" not in pkgs


def test_debian_packages_ubuntu_2204_uses_libasound2():
    info = plat.PlatformInfo(family="debian-family", id="ubuntu", version="22.04")
    pkgs = plat.debian_packages(info)
    assert "libasound2" in pkgs
    assert "libasound2t64" not in pkgs


def test_debian_packages_debian_uses_libasound2():
    info = plat.PlatformInfo(family="debian-family", id="debian", version="12")
    pkgs = plat.debian_packages(info)
    assert "libasound2" in pkgs
    assert "libasound2t64" not in pkgs


def test_suse_packages_is_tuple_of_strings():
    assert isinstance(plat.SUSE_PACKAGES, tuple)
    assert all(isinstance(p, str) and p for p in plat.SUSE_PACKAGES)
    # Spot check: zypper-named Chromium runtime libs.
    assert "mozilla-nss" in plat.SUSE_PACKAGES
    assert "libdrm2" in plat.SUSE_PACKAGES


def test_list_reviewed_against_playwright_suse_matches_pinned_version():
    """Reminds maintainer to review SUSE_PACKAGES when playwright is bumped."""
    import sys

    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib  # type: ignore[no-redef]

    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    deps = pyproject["project"]["dependencies"]
    pw_dep = next(d for d in deps if d.startswith("playwright"))
    pinned = pw_dep.split(">=", 1)[1].split(",", 1)[0].strip()
    reviewed = plat.LIST_REVIEWED_AGAINST_PLAYWRIGHT_SUSE
    nativedeps_url = (
        "https://github.com/microsoft/playwright/blob/main"
        "/packages/playwright-core/src/server/registry/nativeDeps.ts"
    )
    assert reviewed == pinned, (
        f"SUSE_PACKAGES was last reviewed for playwright {reviewed}, "
        f"but pyproject.toml now pins playwright {pinned}. "
        f"Review src/vip/install/platform.py:SUSE_PACKAGES against {nativedeps_url} "
        "and bump LIST_REVIEWED_AGAINST_PLAYWRIGHT_SUSE to match."
    )


def test_list_reviewed_against_playwright_matches_pinned_version():
    """Reminds maintainer to review DEBIAN_PACKAGES when playwright is bumped."""
    import sys

    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib  # type: ignore[no-redef]

    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    deps = pyproject["project"]["dependencies"]
    pw_dep = next(d for d in deps if d.startswith("playwright"))
    # Extract version specifier (e.g. "playwright>=1.50,<2.0" → "1.50,<2.0" → "1.50").
    pinned = pw_dep.split(">=", 1)[1].split(",", 1)[0].strip()
    reviewed = plat.LIST_REVIEWED_AGAINST_PLAYWRIGHT
    nativedeps_url = (
        "https://github.com/microsoft/playwright/blob/main"
        "/packages/playwright-core/src/server/registry/nativeDeps.ts"
    )
    assert reviewed == pinned, (
        f"DEBIAN_PACKAGES was last reviewed for playwright {reviewed}, "
        f"but pyproject.toml now pins playwright {pinned}. "
        f"Review src/vip/install/platform.py:DEBIAN_PACKAGES against {nativedeps_url} "
        "and bump LIST_REVIEWED_AGAINST_PLAYWRIGHT to match."
    )
