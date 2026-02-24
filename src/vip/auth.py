"""Interactive browser authentication for OIDC providers."""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


@dataclass
class InteractiveAuthSession:
    """Manages a browser session for interactive OIDC authentication.

    The browser stays open for the entire pytest session so we can
    clean up the API key after tests complete.
    """

    storage_state_path: Path
    api_key: str | None = None

    _connect_url: str = field(default="", repr=False)
    _key_id: str | None = field(default=None, repr=False)

    def cleanup(self) -> None:
        """Delete the minted API key."""
        if self.api_key and self._connect_url:
            try:
                _delete_api_key(self._connect_url, self.api_key)
            except Exception as exc:
                print(f">>> Warning: Could not delete API key: {exc}")


def start_interactive_auth(connect_url: str) -> InteractiveAuthSession:
    """Launch a headed browser, authenticate via OIDC, and mint a
    Connect API key through the UI.

    The returned session keeps the browser open.  Call ``cleanup()``
    after tests to delete the key and close the browser.
    """
    storage_state_path = Path(tempfile.mkdtemp()) / "vip-auth-state.json"

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()

    # Navigate to Connect login — triggers OIDC redirect
    page.goto(f"{connect_url}/__login__")

    print(f"\n>>> A browser window has opened at {connect_url}")
    print(">>> Please log in through your identity provider.")
    print(">>> The browser will close automatically once testing is done.\n")

    # Poll until login completes (back on Connect, not on login page)
    base = connect_url.rstrip("/")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        try:
            url = page.url
        except Exception:
            break
        if base in url and "/__login__" not in url and "login" not in url.split(base)[-1].lower():
            break
        try:
            page.wait_for_timeout(500)
        except Exception:
            break

    # Mint an API key through the Connect UI
    api_key, key_id = _create_api_key_via_ui(page, connect_url)

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
        _key_id=key_id,
    )


def _create_api_key_via_ui(page: Page, connect_url: str) -> tuple[str | None, str | None]:
    """Navigate the Connect UI to create an API key.

    Returns (api_key, key_id) or (None, None) on failure.
    """
    base = connect_url.rstrip("/")

    try:
        # Navigate to dashboard, then find the API Keys page through the UI
        page.goto(f"{base}/connect/#/")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2_000)

        # Open user dropdown by clicking the user panel area (top-right).
        # Use evaluate to find the clickable element reliably.
        page.evaluate("""() => {
            // Find and click the user avatar/name area in the header
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
        }""")
        page.wait_for_timeout(1_000)

        page.get_by_text("Manage Your API Keys").click(timeout=5_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1_000)

        # Click "+ New API Key"
        page.locator("text=New API Key").first.click(timeout=5_000)
        page.wait_for_timeout(1_000)
        page.screenshot(path="/tmp/vip-new-key-dialog.png")

        # Fill in the key name input
        name_input = page.locator("input[type='text']").first
        name_input.fill("_vip_interactive")
        page.wait_for_timeout(300)

        # Click Create button in the dialog
        page.locator("button:has-text('Create'),button[type='submit']").first.click(timeout=5_000)
        page.wait_for_timeout(1_000)
        page.screenshot(path="/tmp/vip-key-created.png")

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
            return None, None

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

        key_id = None

        return api_key, key_id
    except Exception as exc:
        print(f">>> Warning: Could not create API key via UI: {exc}")
        print(">>> API-based tests may fail. Set VIP_CONNECT_API_KEY.\n")
        return None, None


def _find_key_id(page: Page, api_key: str) -> str | None:
    """Try to find the key ID from the current page state."""
    # The key ID might be in the URL or visible in the key list
    try:
        url = page.url
        # Some Connect versions include the key ID in the URL hash
        if "/api_keys/" in url:
            return url.split("/api_keys/")[-1].split("/")[0].split("#")[0]
    except Exception:
        pass
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
        # Try v1 endpoint, fall back to legacy
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
