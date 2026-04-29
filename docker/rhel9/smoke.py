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
        assert page.title() == "RHEL9 smoke"
        page.fill("#i", "hello from rhel9")
        page.evaluate(
            "document.getElementById('r').textContent = document.getElementById('i').value"
        )
        assert page.text_content("#r") == "hello from rhel9"
        ua = page.evaluate("navigator.userAgent")
        assert "HeadlessChrome" in ua, f"unexpected UA: {ua}"
        page.screenshot(path="/tmp/smoke.png")
        browser.close()
    print("PASS: rhel9 headless chromium smoke")


if __name__ == "__main__":
    main()
