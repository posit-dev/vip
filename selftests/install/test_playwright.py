"""Tests for src/vip/install/playwright.py."""

from __future__ import annotations

from io import StringIO
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


def test_chromium_installed_true_when_expected_revision_present(tmp_path: Path):
    (tmp_path / "chromium-1234").mkdir()
    assert pw.chromium_installed(tmp_path, revision="1234") is True


def test_chromium_installed_false_when_no_chromium(tmp_path: Path):
    (tmp_path / "firefox-9999").mkdir()
    assert pw.chromium_installed(tmp_path, revision="1234") is False


def test_chromium_installed_false_when_dir_missing(tmp_path: Path):
    assert pw.chromium_installed(tmp_path / "does-not-exist", revision="1234") is False


def test_chromium_installed_false_when_only_stale_revision_present(tmp_path: Path):
    """Reproduces the bug where a previous Playwright pin left chromium-1208
    in the cache, but the current pin expects chromium-1217: the cache must
    not be considered satisfied.
    """
    (tmp_path / "chromium-1208").mkdir()
    assert pw.chromium_installed(tmp_path, revision="1217") is False


def test_chromium_installed_uses_expected_revision_by_default(tmp_path: Path, monkeypatch):
    """When no revision is passed, look it up from Playwright's browsers.json."""
    monkeypatch.setattr(pw, "expected_chromium_revision", lambda: "4242")
    (tmp_path / "chromium-4242").mkdir()
    assert pw.chromium_installed(tmp_path) is True


def test_chromium_installed_falls_back_when_revision_unknown(tmp_path: Path, monkeypatch):
    """If the revision cannot be determined (e.g. Playwright not importable),
    fall back to the old behavior of accepting any chromium-* directory so
    users on broken installs aren't blocked from running `vip install`.
    """
    monkeypatch.setattr(pw, "expected_chromium_revision", lambda: None)
    (tmp_path / "chromium-1234").mkdir()
    assert pw.chromium_installed(tmp_path) is True


def test_expected_chromium_revision_reads_browsers_json():
    """The real Playwright in this venv has a browsers.json. Make sure we
    return a non-empty revision string from it."""
    rev = pw.expected_chromium_revision()
    assert rev is not None
    assert rev.isdigit()


class _FakePopen:
    """Drop-in stand-in for subprocess.Popen for testing the streaming filter.

    `stdout` and `stderr` are line-iterable; `wait()` returns `_returncode`.
    """

    def __init__(self, args, *, stdout_text: str = "", stderr_text: str = "", returncode: int = 0):
        self.args = args
        self.stdout = StringIO(stdout_text)
        self.stderr = StringIO(stderr_text)
        self._returncode = returncode

    def wait(self):
        return self._returncode


def _popen_factory(**kwargs):
    """Returns a fake Popen constructor that ignores subprocess.Popen kwargs and
    returns a _FakePopen seeded with the given outputs."""

    def factory(args, **_):
        return _FakePopen(args, **kwargs)

    return factory


def test_install_chromium_invokes_subprocess(monkeypatch):
    calls = []

    def fake_popen(args, **kwargs):
        calls.append(tuple(args))
        return _FakePopen(args)

    monkeypatch.setattr(pw.subprocess, "Popen", fake_popen)
    pw.install_chromium()
    assert calls == [("playwright", "install", "chromium")]


def test_install_chromium_raises_on_failure(monkeypatch):
    monkeypatch.setattr(pw.subprocess, "Popen", _popen_factory(stderr_text="boom\n", returncode=1))
    with pytest.raises(pw.PlaywrightInstallError, match="exit 1"):
        pw.install_chromium()


def test_chromium_installed_false_when_cache_dir_is_a_file(tmp_path: Path):
    file_path = tmp_path / "ms-playwright"
    file_path.write_text("not a directory")
    assert pw.chromium_installed(file_path) is False


def test_install_chromium_raises_when_binary_missing(monkeypatch):
    def fake_popen(args, **kwargs):
        raise FileNotFoundError("playwright not found")

    monkeypatch.setattr(pw.subprocess, "Popen", fake_popen)
    with pytest.raises(pw.PlaywrightInstallError, match="playwright"):
        pw.install_chromium()


def test_install_chromium_filters_beware_preamble_and_replaces(monkeypatch, capsys):
    """RHEL/unsupported-OS install path: BEWARE lines are dropped, vip prints
    its own one-line summary."""
    stderr_text = (
        "BEWARE: your OS is not officially supported by Playwright;\n"
        "downloading fallback build for ubuntu24.04-x64.\n"
    )
    stdout_text = "Downloading Chromium 120 - 150 MB [====>] 100%\n"
    monkeypatch.setattr(
        pw.subprocess,
        "Popen",
        _popen_factory(stdout_text=stdout_text, stderr_text=stderr_text),
    )

    pw.install_chromium()

    out = capsys.readouterr()
    assert "BEWARE" not in out.out + out.err
    assert "officially supported" not in out.out + out.err
    assert "downloading fallback build" not in out.out + out.err
    assert "Downloading Chromium 120" in out.out
    assert "Installed Playwright Chromium" in out.out


def test_install_chromium_forwards_normal_output_unchanged(monkeypatch, capsys):
    """Officially-supported OS: no BEWARE lines, no vip summary printed."""
    stdout_text = "Downloading Chromium 120 - 150 MB [====>] 100%\nChromium downloaded.\n"
    monkeypatch.setattr(pw.subprocess, "Popen", _popen_factory(stdout_text=stdout_text))

    pw.install_chromium()

    out = capsys.readouterr()
    assert "Downloading Chromium 120" in out.out
    assert "Chromium downloaded." in out.out
    # No BEWARE means no vip summary line either.
    assert "Installed Playwright Chromium" not in out.out
