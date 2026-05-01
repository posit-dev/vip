"""Headless Chromium smoke test for RHEL family (UBI-based images).

Mirrors microsoft/playwright#40312's manual test: launches Chromium
headlessly, exercises basic page interaction and JS evaluation, and
takes a screenshot. Exits non-zero on any failure so docker run
propagates the result.
"""

import re
from pathlib import Path

from playwright.sync_api import sync_playwright


def _rhel_major_version() -> str:
    """Read VERSION_ID from /etc/os-release and return the major version digit."""
    try:
        text = Path("/etc/os-release").read_text()
        m = re.search(r'^VERSION_ID="?(\d+)', text, re.MULTILINE)
        if m:
            return m.group(1)
    except OSError:
        pass
    return "unknown"


def main() -> None:
    version = _rhel_major_version()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(
            "data:text/html,<title>RHEL smoke</title><h1 id=h>ok</h1><input id=i><div id=r></div>"
        )
        title = page.title()
        if title != "RHEL smoke":
            raise RuntimeError(f"unexpected title: {title!r}")
        page.fill("#i", "hello from rhel")
        page.evaluate(
            "document.getElementById('r').textContent = document.getElementById('i').value"
        )
        text = page.text_content("#r")
        if text != "hello from rhel":
            raise RuntimeError(f"unexpected DOM text: {text!r}")
        ua = page.evaluate("navigator.userAgent")
        if "HeadlessChrome" not in ua:
            raise RuntimeError(f"unexpected UA: {ua!r}")
        page.screenshot(path="/tmp/smoke.png")
        browser.close()
    print(f"PASS: rhel{version} headless chromium smoke")


if __name__ == "__main__":
    main()
