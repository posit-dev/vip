"""Wrap `playwright install` and detect the browser cache."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import IO


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


def _drain(source: IO[str], sink: IO[str], filtered: list[bool]) -> None:
    """Read lines from source and forward to sink, dropping BEWARE preamble.

    Designed to run in a worker thread per Popen pipe so stdout and stderr stream
    independently without deadlocking on a full pipe buffer. Appends to `filtered`
    when a BEWARE line is dropped (used as a thread-safe boolean flag).
    """
    for line in source:
        if _is_beware_line(line):
            filtered.append(True)
            continue
        sink.write(line)
        sink.flush()


def install_chromium() -> None:
    """Run `playwright install chromium` (no --with-deps). Raises on nonzero exit.

    Streams Playwright's stdout and stderr through line-by-line in real time so
    download progress is visible during the install. Filters the BEWARE preamble
    (printed on RHEL/unsupported OSes) and replaces it with a single
    vip-attributed summary line.
    """
    try:
        proc = subprocess.Popen(
            ["playwright", "install", "chromium"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        raise PlaywrightInstallError(
            f"could not invoke playwright (is it installed?): {exc}"
        ) from exc

    filtered: list[bool] = []
    threads = [
        threading.Thread(target=_drain, args=(proc.stdout, sys.stdout, filtered), daemon=True),
        threading.Thread(target=_drain, args=(proc.stderr, sys.stderr, filtered), daemon=True),
    ]
    for t in threads:
        t.start()
    rc = proc.wait()
    for t in threads:
        t.join()

    if rc != 0:
        raise PlaywrightInstallError(f"playwright install chromium exited with exit {rc}")

    if filtered:
        print(
            "Installed Playwright Chromium (Ubuntu 24.04 fallback build for unsupported-OS hosts)."
        )
