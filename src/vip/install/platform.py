"""Platform detection and pinned package lists for vip install/uninstall."""

from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

_OS_RELEASE_PATH = Path("/etc/os-release")

_RHEL_LIKE = {"rhel", "fedora", "centos", "rocky", "almalinux", "ol"}
_DEBIAN_LIKE = {"debian", "ubuntu"}
_SUSE_LIKE = {"opensuse-leap", "opensuse-tumbleweed", "sles", "suse", "opensuse"}


@dataclass(frozen=True)
class PlatformInfo:
    """Result of detect().

    family is one of: rhel-family, debian-family, suse-family, macos, unsupported.
    """

    family: str
    id: str | None = None
    version: str | None = None
    raw: dict[str, str] | None = None


def detect() -> PlatformInfo:
    """Detect the host platform; never raises."""
    if sys.platform == "darwin":
        return PlatformInfo(family="macos")
    if sys.platform != "linux":
        return PlatformInfo(family="unsupported")
    raw = _read_os_release()
    if not raw:
        return PlatformInfo(family="unsupported")
    distro_id = raw.get("ID", "").strip().lower()
    version = raw.get("VERSION_ID")
    id_like = raw.get("ID_LIKE", "").strip().lower().split()
    candidates = {distro_id, *id_like}
    family = "unsupported"
    if candidates & _RHEL_LIKE:
        family = "rhel-family"
    elif candidates & _DEBIAN_LIKE:
        family = "debian-family"
    elif candidates & _SUSE_LIKE:
        family = "suse-family"
    return PlatformInfo(family=family, id=distro_id or None, version=version, raw=raw)


def _read_os_release() -> dict[str, str]:
    if not _OS_RELEASE_PATH.exists():
        return {}
    out: dict[str, str] = {}
    for line in _OS_RELEASE_PATH.read_text().splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        k, _, v = line.partition("=")
        try:
            out[k.strip()] = " ".join(shlex.split(v))
        except ValueError:
            continue
    return out


# RHEL-family Chromium runtime libs. Single source of truth for the package list.
RHEL_PACKAGES: tuple[str, ...] = (
    "nss",
    "nspr",
    "atk",
    "at-spi2-atk",
    "at-spi2-core",
    "cups-libs",
    "dbus-libs",
    "libdrm",
    "mesa-libgbm",
    "glib2",
    "pango",
    "cairo",
    "libX11",
    "libxcb",
    "libXcomposite",
    "libXdamage",
    "libXext",
    "libXfixes",
    "libxkbcommon",
    "libXrandr",
    "libXtst",
    "libxshmfence",
    "alsa-lib",
)

# Debian/Ubuntu equivalents. Mirrored from Playwright nativeDeps.ts at the version
# below; bump LIST_REVIEWED_AGAINST_PLAYWRIGHT after each playwright pin update.
DEBIAN_PACKAGES: tuple[str, ...] = (
    "libnss3",
    "libnspr4",
    "libatk1.0-0",
    "libatk-bridge2.0-0",
    "libcups2",
    "libdrm2",
    "libxkbcommon0",
    "libxcomposite1",
    "libxdamage1",
    "libxfixes3",
    "libxrandr2",
    "libgbm1",
    "libpango-1.0-0",
    "libcairo2",
    "libasound2",
    "libxshmfence1",
    "libx11-6",
    "libxcb1",
    "libxext6",
    "libdbus-1-3",
    "libglib2.0-0",
)

# Ubuntu 24.04+ renamed libasound2 → libasound2t64 as part of the 64-bit time_t
# transition.  Unlike other t64 renames (libcups2 → libcups2t64) that apt resolves
# automatically, libasound2 became a virtual package with multiple providers, so
# apt refuses to install it directly.  We swap it for the concrete name on >= 24.04.
_T64_LIBASOUND_MIN_VERSION = "24.04"


def _is_ubuntu_like(platform_info: PlatformInfo) -> bool:
    """True when the distro is Ubuntu or an Ubuntu derivative (e.g. Pop!_OS)."""
    if platform_info.id == "ubuntu":
        return True
    raw = platform_info.raw or {}
    return "ubuntu" in raw.get("ID_LIKE", "").lower().split()


def debian_packages(platform_info: PlatformInfo) -> tuple[str, ...]:
    """Return DEBIAN_PACKAGES with version-appropriate substitutions."""
    version = platform_info.version or ""
    if _is_ubuntu_like(platform_info) and version >= _T64_LIBASOUND_MIN_VERSION:
        return tuple("libasound2t64" if p == "libasound2" else p for p in DEBIAN_PACKAGES)
    return DEBIAN_PACKAGES


# When updating the playwright pin in pyproject.toml, review DEBIAN_PACKAGES against
# https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/server/registry/nativeDeps.ts
# and update this value. The selftest enforces that they match.
LIST_REVIEWED_AGAINST_PLAYWRIGHT = "1.40"


# openSUSE/SLES equivalents. Names from `zypper search --provides` against
# opensuse/leap:15. Bump LIST_REVIEWED_AGAINST_PLAYWRIGHT_SUSE after each
# playwright pin update; the selftest enforces parity.
SUSE_PACKAGES: tuple[str, ...] = (
    "mozilla-nss",
    "mozilla-nspr",
    "libatk-1_0-0",
    "libatk-bridge-2_0-0",
    "libcups2",
    "libdrm2",
    "libxkbcommon0",
    "libXcomposite1",
    "libXdamage1",
    "libXfixes3",
    "libXrandr2",
    "libgbm1",
    "libpango-1_0-0",
    "libcairo2",
    "libasound2",
    "libxshmfence1",
    "libX11-6",
    "libxcb1",
    "libXext6",
    "libdbus-1-3",
    "libglib-2_0-0",
    "fontconfig",
    "liberation-fonts",
)

# Mirror of LIST_REVIEWED_AGAINST_PLAYWRIGHT for the SUSE list.
LIST_REVIEWED_AGAINST_PLAYWRIGHT_SUSE = "1.40"
