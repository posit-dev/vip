"""Tests for src/vip/install/playwright.py."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from vip.install import playwright as pw


def test_default_cache_dir_linux(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(pw.sys, "platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    assert pw.default_cache_dir() == tmp_path / ".cache" / "ms-playwright"


def test_default_cache_dir_macos(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(pw.sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    assert pw.default_cache_dir() == tmp_path / "Library" / "Caches" / "ms-playwright"


def test_default_cache_dir_respects_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "custom"))
    assert pw.default_cache_dir() == tmp_path / "custom"


def test_chromium_installed_true_when_dir_present(tmp_path: Path):
    (tmp_path / "chromium-1234").mkdir()
    assert pw.chromium_installed(tmp_path) is True


def test_chromium_installed_false_when_no_chromium(tmp_path: Path):
    (tmp_path / "firefox-9999").mkdir()
    assert pw.chromium_installed(tmp_path) is False


def test_chromium_installed_false_when_dir_missing(tmp_path: Path):
    assert pw.chromium_installed(tmp_path / "does-not-exist") is False


def _ok(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_install_chromium_invokes_subprocess(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(tuple(args))
        return _ok()

    monkeypatch.setattr(pw.subprocess, "run", fake_run)
    pw.install_chromium()
    assert calls == [("playwright", "install", "chromium")]


def test_install_chromium_raises_on_failure(monkeypatch):
    monkeypatch.setattr(pw.subprocess, "run", lambda *a, **kw: _ok(stderr="boom", returncode=1))
    with pytest.raises(pw.PlaywrightInstallError, match="exit 1"):
        pw.install_chromium()


def test_chromium_installed_false_when_cache_dir_is_a_file(tmp_path: Path):
    file_path = tmp_path / "ms-playwright"
    file_path.write_text("not a directory")
    assert pw.chromium_installed(file_path) is False


def test_install_chromium_raises_when_binary_missing(monkeypatch):
    def fake_run(args, **kwargs):
        raise FileNotFoundError("playwright not found")

    monkeypatch.setattr(pw.subprocess, "run", fake_run)
    with pytest.raises(pw.PlaywrightInstallError, match="playwright"):
        pw.install_chromium()


def test_install_chromium_filters_beware_preamble_and_replaces(monkeypatch, capsys):
    """RHEL/unsupported-OS install path: BEWARE lines are dropped, vip prints
    its own one-line summary."""
    stderr = (
        "BEWARE: your OS is not officially supported by Playwright;\n"
        "downloading fallback build for ubuntu24.04-x64.\n"
    )
    stdout = "Downloading Chromium 120 - 150 MB [====>] 100%\n"
    monkeypatch.setattr(pw.subprocess, "run", lambda *a, **kw: _ok(stdout=stdout, stderr=stderr))

    pw.install_chromium()

    out = capsys.readouterr()
    assert "BEWARE" not in out.out + out.err
    assert "officially supported" not in out.out + out.err
    assert "downloading fallback build" not in out.out + out.err
    assert "Downloading Chromium 120" in out.out
    assert "Installed Playwright Chromium" in out.out


def test_install_chromium_forwards_normal_output_unchanged(monkeypatch, capsys):
    """Officially-supported OS: no BEWARE lines, no vip summary printed."""
    stdout = "Downloading Chromium 120 - 150 MB [====>] 100%\nChromium downloaded.\n"
    monkeypatch.setattr(pw.subprocess, "run", lambda *a, **kw: _ok(stdout=stdout))

    pw.install_chromium()

    out = capsys.readouterr()
    assert "Downloading Chromium 120" in out.out
    assert "Chromium downloaded." in out.out
    # No BEWARE means no vip summary line either.
    assert "Installed Playwright Chromium" not in out.out
