"""Interactive browser authentication for OIDC providers.

Opens a headed Chromium browser for the user to complete an OIDC login
flow, mints a temporary Connect API key via the UI, saves the browser
storage state, then closes the browser before tests start.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


@dataclass
class InteractiveAuthSession:
    """Result of an interactive OIDC authentication flow.

    Holds the saved browser storage state (for Playwright tests) and a
    minted Connect API key (for httpx API tests).  Call ``cleanup()``
    after the test session to delete the temporary API key.
    """

    storage_state_path: Path
    api_key: str | None = None

    _connect_url: str = field(default="", repr=False)
    _tmpdir: str = field(default="", repr=False)

    def cleanup(self) -> None:
        """Delete the minted API key and remove the temp directory."""
        if self.api_key and self._connect_url:
            try:
                _delete_api_key(self._connect_url, self.api_key)
            except Exception as exc:
                print(f">>> Warning: Could not delete API key: {exc}")

        if self._tmpdir and os.path.isdir(self._tmpdir):
            shutil.rmtree(self._tmpdir, ignore_errors=True)


def start_interactive_auth(connect_url: str) -> InteractiveAuthSession:
    """Launch a headed browser, authenticate via OIDC, and mint a
    Connect API key through the UI.

    The browser is closed before this function returns.  pytest-playwright
    creates its own browser instance using the saved storage state.
    """
    tmpdir = tempfile.mkdtemp(prefix="vip-auth-")
    storage_state_path = Path(tmpdir) / "vip-auth-state.json"
    # Restrict permissions on the temp dir (contains session cookies).
    os.chmod(tmpdir, 0o700)

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()

    # Navigate to Connect login — triggers OIDC redirect
    page.goto(f"{connect_url}/__login__")

    print(f"\n>>> A browser window has opened at {connect_url}")
    print(">>> Please log in through your identity provider.")
    print(">>> The browser will close automatically after login.\n")

    # Poll until login completes (back on Connect, not on login page)
    base = connect_url.rstrip("/")
    deadline = time.monotonic() + 300
    login_completed = False
    while time.monotonic() < deadline:
        try:
            url = page.url
        except Exception:
            break
        if base in url and "/__login__" not in url:
            login_completed = True
            break
        try:
            page.wait_for_timeout(500)
        except Exception:
            break

    if not login_completed:
        browser.close()
        pw.stop()
        raise RuntimeError(
            "Login did not complete within 5 minutes. "
            "Please rerun and complete authentication in the browser window."
        )

    # Mint an API key through the Connect UI
    api_key = _create_api_key_via_ui(page, connect_url)

    # Save storage state for Playwright test contexts
    context.storage_state(path=str(storage_state_path))

    # Close the browser and Playwright before tests start.
    # pytest-playwright will create its own instance using the saved
    # storage state.  Keeping ours open causes "Sync API inside asyncio
    # loop" errors.
    browser.close()
    pw.stop()

    return InteractiveAuthSession(
        storage_state_path=storage_state_path,
        api_key=api_key,
        _connect_url=connect_url,
        _tmpdir=tmpdir,
    )


def _create_api_key_via_ui(page: Page, connect_url: str) -> str | None:
    """Navigate the Connect UI to create an API key.

    Returns the API key string, or None on failure.
    """
    base = connect_url.rstrip("/")

    try:
        # Navigate to the Connect dashboard
        page.goto(f"{base}/connect/#/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2_000)

        # Open user dropdown by clicking the user panel area (top-right).
        # Uses JS to find the element by position since Connect versions
        # vary in their markup.
        page.evaluate(
            """() => {
            const els = document.querySelectorAll('a, button, [role="button"], span');
            for (const el of els) {
                const rect = el.getBoundingClientRect();
                if (rect.right > window.innerWidth - 200 && rect.top < 60) {
                    const text = el.textContent || '';
                    if (text.includes('.') && text.length < 30) {
                        el.click();
                        return;
                    }
                }
            }
        }"""
        )
        page.wait_for_timeout(1_000)

        page.get_by_text("Manage Your API Keys").click(timeout=5_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1_000)

        # Click "+ New API Key"
        page.locator("text=New API Key").first.click(timeout=5_000)
        page.wait_for_timeout(1_000)

        # Fill in the key name
        name_input = page.locator("input[type='text']").first
        name_input.fill("_vip_interactive")
        page.wait_for_timeout(300)

        # Click Create button
        page.locator("button:has-text('Create'),button[type='submit']").first.click(timeout=5_000)
        page.wait_for_timeout(1_000)

        # Extract the generated key — Connect shows it in a read-only
        # input, a code block, or a text element in the dialog
        api_key = None
        for selector in [
            "input[readonly]",
            "code",
            ".api-key-value",
            "pre",
            "[data-automation='api-key-value']",
        ]:
            el = page.locator(selector).first
            try:
                val = el.input_value(timeout=2_000)
            except Exception:
                try:
                    val = el.text_content(timeout=2_000)
                except Exception:
                    continue
            if val and len(val) > 20:
                api_key = val.strip()
                break

        if not api_key:
            print(">>> Warning: Could not read API key from UI.")
            print(">>> API-based tests may fail. Set VIP_CONNECT_API_KEY.\n")
            return None

        print(">>> Connect API key created via UI.\n")

        # Close the dialog
        try:
            page.locator(
                "button:has-text('Close'),"
                "button:has-text('Done'),"
                "button:has-text('OK'),"
                "[aria-label='Close']"
            ).first.click(timeout=3_000)
        except Exception:
            page.keyboard.press("Escape")

        return api_key
    except Exception as exc:
        print(f">>> Warning: Could not create API key via UI: {exc}")
        print(">>> API-based tests may fail. Set VIP_CONNECT_API_KEY.\n")
        return None


def _delete_api_key(connect_url: str, api_key: str) -> None:
    """Delete the VIP API key using the key itself for authentication."""
    import httpx

    base = connect_url.rstrip("/")
    with httpx.Client(
        base_url=f"{base}/__api__",
        headers={"Authorization": f"Key {api_key}"},
        timeout=10.0,
    ) as client:
        for keys_path in ("/v1/user/api_keys", "/keys"):
            resp = client.get(keys_path)
            if resp.status_code == 404:
                continue
            if resp.is_success:
                for k in resp.json():
                    if k.get("name") == "_vip_interactive":
                        client.delete(f"{keys_path}/{k['id']}")
                        print(">>> API key deleted.\n")
                        return
                break
        print(">>> Warning: Could not find API key to delete.\n")
