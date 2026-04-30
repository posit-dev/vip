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


def test_install_chromium_invokes_subprocess(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(tuple(args))
        return subprocess.CompletedProcess(args=args, returncode=0)

    monkeypatch.setattr(pw.subprocess, "run", fake_run)
    pw.install_chromium()
    assert calls == [("playwright", "install", "chromium")]


def test_install_chromium_raises_on_failure(monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=1, stderr="boom")

    monkeypatch.setattr(pw.subprocess, "run", fake_run)
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
