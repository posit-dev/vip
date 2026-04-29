"""Headless Chromium smoke test for RHEL 9.

Mirrors microsoft/playwright#40312's manual test: launches Chromium
headlessly, exercises basic page interaction and JS evaluation, and
takes a screenshot. Exits non-zero on any failure so docker run
propagates the result.
"""

from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(
            "data:text/html,<title>RHEL9 smoke</title><h1 id=h>ok</h1><input id=i><div id=r></div>"
        )
        title = page.title()
        if title != "RHEL9 smoke":
            raise RuntimeError(f"unexpected title: {title!r}")
        page.fill("#i", "hello from rhel9")
        page.evaluate(
            "document.getElementById('r').textContent = document.getElementById('i').value"
        )
        text = page.text_content("#r")
        if text != "hello from rhel9":
            raise RuntimeError(f"unexpected DOM text: {text!r}")
        ua = page.evaluate("navigator.userAgent")
        if "HeadlessChrome" not in ua:
            raise RuntimeError(f"unexpected UA: {ua!r}")
        page.screenshot(path="/tmp/smoke.png")
        browser.close()
    print("PASS: rhel9 headless chromium smoke")


if __name__ == "__main__":
    main()
