"""Headless Chromium smoke test usable on any vip-supported platform.

Mirrors microsoft/playwright#40312's manual test: launches Chromium
headlessly, exercises basic page interaction and JS evaluation, and
takes a screenshot. Exits non-zero on any failure so docker run /
the GitHub Actions step propagates the result.
"""

import platform as _stdplatform
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def _platform_label() -> str:
    """Best-effort short label like 'rhel9', 'leap15', 'macos-14.5', or 'unknown'."""
    if sys.platform == "darwin":
        ver = _stdplatform.mac_ver()[0] or "unknown"
        return f"macos-{ver}"
    try:
        text = Path("/etc/os-release").read_text()
    except OSError:
        return "unknown"
    distro_id = ""
    version_major = ""
    m_id = re.search(r'^ID="?([^"\n]+)"?', text, re.MULTILINE)
    if m_id:
        distro_id = m_id.group(1).strip()
    m_ver = re.search(r'^VERSION_ID="?(\d+)', text, re.MULTILINE)
    if m_ver:
        version_major = m_ver.group(1)
    label = f"{distro_id}{version_major}".strip()
    return label or "unknown"


def main() -> None:
    label = _platform_label()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chromium-headless-shell")
        page = browser.new_page()
        page.goto(
            "data:text/html,<title>vip smoke</title><h1 id=h>ok</h1><input id=i><div id=r></div>"
        )
        title = page.title()
        if title != "vip smoke":
            raise RuntimeError(f"unexpected title: {title!r}")
        page.fill("#i", f"hello from {label}")
        page.evaluate(
            "document.getElementById('r').textContent = document.getElementById('i').value"
        )
        text = page.text_content("#r")
        if text != f"hello from {label}":
            raise RuntimeError(f"unexpected DOM text: {text!r}")
        ua = page.evaluate("navigator.userAgent")
        if "HeadlessChrome" not in ua:
            raise RuntimeError(f"unexpected UA: {ua!r}")
        page.screenshot(path="/tmp/smoke.png")
        browser.close()
    print(f"PASS: {label} headless chromium smoke")


if __name__ == "__main__":
    main()
