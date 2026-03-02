"""Interactive browser authentication for OIDC providers.

Opens a headed Chromium browser for the user to complete an OIDC login
flow, mints a temporary Connect API key via the UI, saves the browser
storage state, then closes the browser before tests start.

.. warning::

    The UI automation in ``_create_api_key_via_ui`` is inherently fragile
    and may break across Connect versions.  If Connect gains a programmatic
    endpoint for temporary key creation, this should be replaced.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

# Prefix for VIP-managed API keys.  A timestamp is appended per run.
_KEY_NAME_PREFIX = "_vip_interactive_"


@dataclass
class InteractiveAuthSession:
    """Result of an interactive OIDC authentication flow.

    Holds the saved browser storage state (for Playwright tests) and a
    minted Connect API key (for httpx API tests).  Call ``cleanup()``
    after the test session to delete the temporary API key.
    """

    storage_state_path: Path
    api_key: str | None = None
    key_name: str = ""

    _connect_url: str = field(default="", repr=False)
    _tmpdir: str = field(default="", repr=False)

    def cleanup(self) -> None:
        """Delete the minted API key and remove the temp directory."""
        if self.api_key and self._connect_url:
            try:
                _delete_api_key(self._connect_url, self.api_key, self.key_name)
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
    os.chmod(tmpdir, 0o700)

    key_name = f"{_KEY_NAME_PREFIX}{int(time.time())}"

    pw = None
    browser = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        page.goto(f"{connect_url}/__login__")

        print(f"\n>>> A browser window has opened at {connect_url}")
        print(">>> Please log in through your identity provider.")
        print(">>> The browser will close automatically after login.\n")

        # Poll until login completes
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
            raise RuntimeError(
                "Login did not complete within 5 minutes. "
                "Please rerun and complete authentication in the browser window."
            )

        api_key = _create_api_key_via_ui(page, connect_url, key_name)
        context.storage_state(path=str(storage_state_path))

        return InteractiveAuthSession(
            storage_state_path=storage_state_path,
            api_key=api_key,
            key_name=key_name,
            _connect_url=connect_url,
            _tmpdir=tmpdir,
        )
    except Exception:
        if tmpdir and os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if pw is not None:
            try:
                pw.stop()
            except Exception:
                pass


def _create_api_key_via_ui(page: Page, connect_url: str, key_name: str) -> str | None:
    """Navigate the Connect UI to create an API key.

    Also deletes any orphaned ``_vip_interactive_*`` keys left over from
    previous runs that crashed before cleanup.

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

        # Delete orphaned VIP keys from previous runs
        _delete_orphaned_keys(page)

        # Click "+ New API Key"
        page.locator("text=New API Key").first.click(timeout=5_000)
        page.wait_for_timeout(1_000)

        # Fill in the key name
        name_input = page.locator("input[type='text']").first
        name_input.fill(key_name)
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
            print(">>> Warning: Could not read API key from Connect UI.")
            print(">>> Set VIP_CONNECT_API_KEY manually for API-based tests.\n")
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
        print(">>> Set VIP_CONNECT_API_KEY manually for API-based tests.\n")
        return None


def _delete_orphaned_keys(page: Page) -> None:
    """Delete any leftover _vip_interactive_* keys visible on the API Keys page."""
    try:
        rows = page.locator("tr, [role='row']").all()
        for row in rows:
            text = row.text_content() or ""
            if _KEY_NAME_PREFIX in text:
                delete_btn = row.locator(
                    "button[aria-label='Delete'], button:has-text('Delete'), [title='Delete']"
                ).first
                try:
                    delete_btn.click(timeout=2_000)
                    # Confirm deletion if a dialog appears
                    page.locator("button:has-text('Yes'),button:has-text('Delete')").first.click(
                        timeout=2_000
                    )
                    page.wait_for_timeout(500)
                except Exception:
                    pass
    except Exception:
        pass  # Best-effort cleanup of orphans


def _delete_api_key(connect_url: str, api_key: str, key_name: str) -> None:
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
            if not resp.is_success:
                print(f">>> Warning: {keys_path} returned HTTP {resp.status_code}")
                continue
            for k in resp.json():
                if k.get("name") == key_name:
                    del_resp = client.delete(f"{keys_path}/{k['id']}")
                    if del_resp.is_success:
                        print(">>> API key deleted.\n")
                    else:
                        print(
                            f">>> Warning: DELETE {keys_path}/{k['id']}"
                            f" returned {del_resp.status_code}"
                        )
                    return
            break
        print(">>> Warning: Could not find API key to delete.\n")
