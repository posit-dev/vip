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
