"""Wrappers over rpm and dpkg-query for detecting installed packages."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable


class PackageQueryError(Exception):
    """Raised when the package manager binary is unavailable on the host."""


def installed_rpm(names: Iterable[str]) -> set[str]:
    """Return the subset of `names` that `rpm -q` reports as installed."""
    present: set[str] = set()
    for name in names:
        try:
            cp = subprocess.run(["rpm", "-q", name], capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            raise PackageQueryError(
                "rpm not found on PATH; can't query RHEL-family package state"
            ) from exc
        if cp.returncode == 0:
            present.add(name)
    return present


def installed_dpkg(names: Iterable[str]) -> set[str]:
    """Return the subset of `names` that dpkg-query reports as 'install ok installed'."""
    present: set[str] = set()
    for name in names:
        try:
            cp = subprocess.run(
                ["dpkg-query", "-W", "-f=${Status}", name],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise PackageQueryError(
                "dpkg-query not found on PATH; can't query Debian-family package state"
            ) from exc
        parts = cp.stdout.strip().split()
        if cp.returncode == 0 and len(parts) == 3 and parts[1] == "ok" and parts[2] == "installed":
            present.add(name)
    return present
