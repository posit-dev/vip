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


def _run_dpkg_query(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise PackageQueryError(
            "dpkg-query not found on PATH; can't query Debian-family package state"
        ) from exc


def _is_installed_status(status: str) -> bool:
    parts = status.split()
    return len(parts) == 3 and parts[1] == "ok" and parts[2] == "installed"


def _parse_provides(field: str) -> set[str]:
    """Split a dpkg Provides field into bare names, dropping version qualifiers.

    dpkg writes entries like "libcups2 (= 2.4.7), libcups-2" -- comma-separated,
    each optionally followed by a " (relop version)" qualifier.
    """
    names: set[str] = set()
    for entry in field.split(","):
        name = entry.strip().split(" (", 1)[0].strip()
        if name:
            names.add(name)
    return names


def _provided_names() -> set[str]:
    """Return every name any installed dpkg package declares in Provides.

    Queried once per `installed_dpkg()` call across the whole package database,
    not per requested name -- `dpkg-query -W` only matches real package names, so
    there is no per-name query that could resolve a purely virtual/Provides name
    directly (see `installed_dpkg`).
    """
    cp = _run_dpkg_query(["dpkg-query", "-W", "-f=${Status}\t${Provides}\n"])
    if cp.returncode != 0:
        return set()
    provided: set[str] = set()
    for line in cp.stdout.splitlines():
        status, _, provides = line.partition("\t")
        if _is_installed_status(status):
            provided |= _parse_provides(provides)
    return provided


def installed_dpkg(names: Iterable[str]) -> set[str]:
    """Return the subset of `names` that dpkg reports as installed.

    A name counts as installed when dpkg has it as a real package in
    'install ok installed' state, or when such a package declares it in
    Provides. Ubuntu 24.04's 64-bit time_t transition renamed libcups2 to
    libcups2t64 and friends, keeping the old names only as Provides, so
    querying the old name directly reports not-installed even though apt
    installed it successfully (#621).
    """
    present: set[str] = set()
    unresolved: list[str] = []
    for name in names:
        cp = _run_dpkg_query(["dpkg-query", "-W", "-f=${Status}", name])
        if cp.returncode == 0 and _is_installed_status(cp.stdout.strip()):
            present.add(name)
        else:
            unresolved.append(name)
    if unresolved:
        provided = _provided_names()
        present |= {name for name in unresolved if name in provided}
    return present
