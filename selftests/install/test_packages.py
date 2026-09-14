"""Tests for src/vip/install/packages.py."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

import pytest

from vip.install import packages as pkg


class FakeRun:
    """Minimal subprocess.run replacement that returns canned output per command."""

    def __init__(self, responses: dict[tuple[str, ...], subprocess.CompletedProcess]):
        self.responses = responses
        self.calls: list[Sequence[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(tuple(args))
        try:
            return self.responses[tuple(args)]
        except KeyError as exc:
            raise AssertionError(f"Unexpected subprocess call: {args!r}") from exc


def _ok(stdout="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_installed_rpm_filters_to_present(monkeypatch):
    fake = FakeRun(
        {
            ("rpm", "-q", "nss"): _ok("nss-3.79.0-1.el9.x86_64\n"),
            ("rpm", "-q", "libdrm"): _ok("package libdrm is not installed\n", returncode=1),
            ("rpm", "-q", "alsa-lib"): _ok("alsa-lib-1.2.7-2.el9.x86_64\n"),
        }
    )
    monkeypatch.setattr(pkg.subprocess, "run", fake)
    result = pkg.installed_rpm(("nss", "libdrm", "alsa-lib"))
    assert result == {"nss", "alsa-lib"}


def test_installed_dpkg_filters_to_present(monkeypatch):
    fake = FakeRun(
        {
            ("dpkg-query", "-W", "-f=${Status}", "libnss3"): _ok("install ok installed"),
            ("dpkg-query", "-W", "-f=${Status}", "libdrm2"): _ok(
                "deinstall ok config-files", returncode=1
            ),
            ("dpkg-query", "-W", "-f=${Status}", "libcups2"): _ok("install ok installed"),
            # libdrm2 isn't resolved directly, so installed_dpkg falls back to the
            # bulk Provides query; no installed package provides it here.
            ("dpkg-query", "-W", "-f=${Status}\t${Provides}\n"): _ok(
                "install ok installed\tsome-other-name\n"
            ),
        }
    )
    monkeypatch.setattr(pkg.subprocess, "run", fake)
    result = pkg.installed_dpkg(("libnss3", "libdrm2", "libcups2"))
    assert result == {"libnss3", "libcups2"}


def test_installed_rpm_handles_missing_rpm_binary(monkeypatch):
    def boom(*a, **kw):
        raise FileNotFoundError("rpm")

    monkeypatch.setattr(pkg.subprocess, "run", boom)
    with pytest.raises(pkg.PackageQueryError, match="rpm"):
        pkg.installed_rpm(("nss",))


def test_installed_dpkg_handles_missing_dpkg_binary(monkeypatch):
    def boom(*a, **kw):
        raise FileNotFoundError("dpkg-query")

    monkeypatch.setattr(pkg.subprocess, "run", boom)
    with pytest.raises(pkg.PackageQueryError, match="dpkg-query"):
        pkg.installed_dpkg(("libnss3",))


def test_installed_rpm_empty_input_returns_empty(monkeypatch):
    monkeypatch.setattr(pkg.subprocess, "run", FakeRun({}))
    assert pkg.installed_rpm(()) == set()


def test_installed_dpkg_empty_input_returns_empty(monkeypatch):
    monkeypatch.setattr(pkg.subprocess, "run", FakeRun({}))
    assert pkg.installed_dpkg(()) == set()


def test_installed_dpkg_accepts_hold_ok_installed(monkeypatch):
    fake = FakeRun(
        {
            ("dpkg-query", "-W", "-f=${Status}", "libdrm2"): _ok("hold ok installed"),
        }
    )
    monkeypatch.setattr(pkg.subprocess, "run", fake)
    result = pkg.installed_dpkg(("libdrm2",))
    assert "libdrm2" in result


# --- #621: Ubuntu 24.04 t64-renamed packages ------------------------------------
#
# `dpkg-query -W -f='${Status}' <name>` only matches real package names -- it does
# not resolve virtual/Provides names. Ubuntu 24.04's 64-bit time_t transition
# renamed several libraries (libcups2 -> libcups2t64, etc.), keeping the old name
# only as a `Provides` entry on the renamed package, so querying the old name
# directly reports nothing even though apt satisfied it. A per-name query for the
# old name can never see this (dpkg-query has no real package by that name to
# match), so detection has to fall back to a single bulk query of every installed
# package's Provides field, once per `installed_dpkg()` call -- not per name, and
# not a hand-maintained rename table.

_BULK_QUERY = ("dpkg-query", "-W", "-f=${Status}\t${Provides}\n")


def test_installed_dpkg_detects_real_package_installed(monkeypatch):
    """Case 1: old name installed as a real package -> detected (regression guard)."""
    fake = FakeRun(
        {
            ("dpkg-query", "-W", "-f=${Status}", "libcups2"): _ok("install ok installed"),
        }
    )
    monkeypatch.setattr(pkg.subprocess, "run", fake)
    result = pkg.installed_dpkg(("libcups2",))
    assert result == {"libcups2"}


def test_installed_dpkg_detects_name_present_only_as_provides(monkeypatch):
    """Case 2 (the bug): old name is not a real package, only Provides of libcups2t64."""
    fake = FakeRun(
        {
            ("dpkg-query", "-W", "-f=${Status}", "libcups2"): subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="dpkg-query: no packages found matching"
            ),
            _BULK_QUERY: _ok("install ok installed\tlibcups2\n"),
        }
    )
    monkeypatch.setattr(pkg.subprocess, "run", fake)
    result = pkg.installed_dpkg(("libcups2",))
    assert result == {"libcups2"}


def test_installed_dpkg_absent_package_not_detected(monkeypatch):
    """Case 3: package genuinely absent -> not detected."""
    fake = FakeRun(
        {
            ("dpkg-query", "-W", "-f=${Status}", "libnonexistent9"): subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="dpkg-query: no packages found matching"
            ),
            _BULK_QUERY: _ok("install ok installed\tlibcups2\n"),
        }
    )
    monkeypatch.setattr(pkg.subprocess, "run", fake)
    result = pkg.installed_dpkg(("libnonexistent9",))
    assert result == set()


def test_installed_dpkg_provides_with_version_qualifier(monkeypatch):
    """Case 4: a Provides field with a version qualifier -> detected.

    dpkg writes `libcups2 (= 2.4.7)`; a naive split on `,` leaves the
    qualifier attached to the name.
    """
    fake = FakeRun(
        {
            ("dpkg-query", "-W", "-f=${Status}", "libcups2"): subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="dpkg-query: no packages found matching"
            ),
            _BULK_QUERY: _ok("install ok installed\tlibcups2 (= 2.4.7)\n"),
        }
    )
    monkeypatch.setattr(pkg.subprocess, "run", fake)
    result = pkg.installed_dpkg(("libcups2",))
    assert result == {"libcups2"}


def test_installed_dpkg_provides_multiple_names(monkeypatch):
    """Case 5: a Provides field listing several names -> both detected."""
    fake = FakeRun(
        {
            ("dpkg-query", "-W", "-f=${Status}", "libcups2"): subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="dpkg-query: no packages found matching"
            ),
            ("dpkg-query", "-W", "-f=${Status}", "libcups-2"): subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="dpkg-query: no packages found matching"
            ),
            _BULK_QUERY: _ok("install ok installed\tlibcups2, libcups-2\n"),
        }
    )
    monkeypatch.setattr(pkg.subprocess, "run", fake)
    result = pkg.installed_dpkg(("libcups2", "libcups-2"))
    assert result == {"libcups2", "libcups-2"}


def test_installed_dpkg_deinstalled_config_files_not_detected(monkeypatch):
    """Case 6: status 'deinstall ok config-files' -> not detected (present but removed)."""
    fake = FakeRun(
        {
            ("dpkg-query", "-W", "-f=${Status}", "libcups2"): _ok(
                "deinstall ok config-files", returncode=1
            ),
            _BULK_QUERY: _ok("deinstall ok config-files\tlibcups2\n"),
        }
    )
    monkeypatch.setattr(pkg.subprocess, "run", fake)
    result = pkg.installed_dpkg(("libcups2",))
    assert result == set()


def test_installed_dpkg_missing_binary_still_raises(monkeypatch):
    """Case 7: dpkg-query missing from PATH -> still raises PackageQueryError."""

    def boom(*a, **kw):
        raise FileNotFoundError("dpkg-query")

    monkeypatch.setattr(pkg.subprocess, "run", boom)
    with pytest.raises(pkg.PackageQueryError, match="dpkg-query"):
        pkg.installed_dpkg(("libcups2",))


def test_installed_dpkg_nonzero_exit_treated_as_not_installed(monkeypatch):
    """Case 8: dpkg-query exiting non-zero -> nothing installed, not a crash."""
    fake = FakeRun(
        {
            ("dpkg-query", "-W", "-f=${Status}", "libcups2"): subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="no packages found matching libcups2"
            ),
            _BULK_QUERY: subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="dpkg-query: no packages installed"
            ),
        }
    )
    monkeypatch.setattr(pkg.subprocess, "run", fake)
    result = pkg.installed_dpkg(("libcups2",))
    assert result == set()


def test_installed_dpkg_detects_all_reported_t64_packages(monkeypatch):
    """Case 9: the issue's literal reproduction -- all four reported packages are
    detected via their t64 package's Provides, with no rename table involved."""
    old_names = ("libatk1.0-0", "libatk-bridge2.0-0", "libcups2", "libglib2.0-0")
    t64_names = ("libatk1.0-0t64", "libatk-bridge2.0-0t64", "libcups2t64", "libglib2.0-0t64")

    responses = {
        ("dpkg-query", "-W", "-f=${Status}", name): subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="dpkg-query: no packages found matching"
        )
        for name in old_names
    }
    bulk_lines = "\n".join(
        f"install ok installed\t{old_name}" for old_name, _ in zip(old_names, t64_names)
    )
    responses[_BULK_QUERY] = _ok(bulk_lines + "\n")
    fake = FakeRun(responses)
    monkeypatch.setattr(pkg.subprocess, "run", fake)
    result = pkg.installed_dpkg(old_names)
    assert result == set(old_names)
