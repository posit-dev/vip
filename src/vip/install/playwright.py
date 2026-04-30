"""Wrap `playwright install` and detect the browser cache."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


class PlaywrightInstallError(Exception):
    """Raised when `playwright install chromium` exits nonzero."""


# Playwright prints a 2-line BEWARE preamble on every unsupported-OS install
# (e.g. RHEL family). It's accurate but alarming; we suppress it and replace
# with a vip-friendly summary line so users aren't startled by Playwright's
# wording every time they run `vip install`.
_BEWARE_PATTERNS = (
    re.compile(r"^BEWARE\b.*officially supported", re.IGNORECASE),
    re.compile(r"^downloading fallback build", re.IGNORECASE),
)


def default_cache_dir() -> Path:
    """Return the directory Playwright uses to cache browser binaries.

    Honors PLAYWRIGHT_BROWSERS_PATH if set, otherwise falls back to per-OS defaults.
    """
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env:
        return Path(env)
    home = Path(os.environ.get("HOME", str(Path.home())))
    if sys.platform == "darwin":
        return home / "Library" / "Caches" / "ms-playwright"
    return home / ".cache" / "ms-playwright"


def chromium_installed(cache_dir: Path) -> bool:
    """Return True if any `chromium-*` directory exists under cache_dir."""
    if not cache_dir.is_dir():
        return False
    return any(p.name.startswith("chromium-") for p in cache_dir.iterdir() if p.is_dir())


def _is_beware_line(line: str) -> bool:
    stripped = line.strip()
    return any(p.match(stripped) for p in _BEWARE_PATTERNS)


def _forward_filtered(text: str, stream) -> bool:
    """Write text to stream, dropping BEWARE-preamble lines. Returns True if any
    BEWARE line was filtered."""
    filtered = False
    for line in text.splitlines(keepends=True):
        if _is_beware_line(line):
            filtered = True
            continue
        stream.write(line)
    stream.flush()
    return filtered


def install_chromium() -> None:
    """Run `playwright install chromium` (no --with-deps). Raises on nonzero exit.

    Filters Playwright's BEWARE-preamble output (printed on RHEL/unsupported OSes)
    and replaces it with a single vip-attributed summary line.
    """
    try:
        cp = subprocess.run(
            ["playwright", "install", "chromium"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise PlaywrightInstallError(
            f"could not invoke playwright (is it installed?): {exc}"
        ) from exc

    filtered = _forward_filtered(cp.stdout, sys.stdout)
    filtered = _forward_filtered(cp.stderr, sys.stderr) or filtered

    if cp.returncode != 0:
        raise PlaywrightInstallError(
            f"playwright install chromium exited with exit {cp.returncode}"
        )

    if filtered:
        print(
            "Installed Playwright Chromium (Ubuntu 24.04 fallback build for unsupported-OS hosts)."
        )
