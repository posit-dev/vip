"""Wrap `playwright install` and detect the browser cache."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class PlaywrightInstallError(Exception):
    """Raised when `playwright install chromium` exits nonzero."""


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
    if not cache_dir.exists():
        return False
    return any(p.name.startswith("chromium-") for p in cache_dir.iterdir() if p.is_dir())


def install_chromium() -> None:
    """Run `playwright install chromium` (no --with-deps). Raises on nonzero exit."""
    cp = subprocess.run(
        ["playwright", "install", "chromium"],
        check=False,
    )
    if cp.returncode != 0:
        raise PlaywrightInstallError(
            f"playwright install chromium exited with exit {cp.returncode}"
        )
