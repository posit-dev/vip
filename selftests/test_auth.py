"""Tests for vip.auth module — headless auth validation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from vip.auth import AuthConfigError, start_headless_auth


class TestStartHeadlessAuthValidation:
    def test_no_urls_raises_even_with_warm_cache(self, tmp_path):
        """URL validation must run before cache lookup."""
        # Create a fake cache file that would be valid.
        cache = tmp_path / ".vip-auth-cache.json"
        cache.write_text("{}")
        cache.touch()

        with pytest.raises(AuthConfigError, match="at least one product URL"):
            start_headless_auth(
                connect_url=None,
                workbench_url=None,
                idp="keycloak",
                username="user",
                password="pass",
                cache_path=cache,
            )

    def test_no_urls_raises_without_cache(self):
        with pytest.raises(AuthConfigError, match="at least one product URL"):
            start_headless_auth()


class TestStartHeadlessAuthPlaywrightErrors:
    """Playwright failures during login should surface as AuthConfigError."""

    def _make_playwright_stub(self, page_goto_exc: Exception) -> MagicMock:
        """Stub sync_playwright() whose page.goto() raises the given exception."""
        pw = MagicMock()
        browser = pw.start.return_value.chromium.launch.return_value
        page = browser.new_context.return_value.new_page.return_value
        page.goto.side_effect = page_goto_exc
        return pw

    def test_timeout_during_login_becomes_auth_config_error(self):
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        stub = self._make_playwright_stub(PlaywrightTimeoutError("timed out"))
        with patch("vip.auth.sync_playwright", return_value=stub):
            with pytest.raises(AuthConfigError, match="timed out"):
                start_headless_auth(
                    connect_url="https://c.example.com",
                    username="user",
                    password="pass",
                )

    def test_playwright_error_during_login_becomes_auth_config_error(self):
        from playwright.sync_api import Error as PlaywrightError

        stub = self._make_playwright_stub(PlaywrightError("net::ERR_NAME_NOT_RESOLVED"))
        with patch("vip.auth.sync_playwright", return_value=stub):
            with pytest.raises(AuthConfigError, match="failed during login"):
                start_headless_auth(
                    connect_url="https://c.example.com",
                    username="user",
                    password="pass",
                )

    def test_missing_chromium_system_deps_gives_remediation(self):
        """Missing host libraries at chromium launch must surface the
        ``playwright install --with-deps chromium`` remediation command
        (see issue #169)."""
        from playwright.sync_api import Error as PlaywrightError

        pw = MagicMock()
        pw.start.return_value.chromium.launch.side_effect = PlaywrightError(
            "Host system is missing dependencies to run browsers.\n"
            "Please install them with the following command:\n"
            "    sudo playwright install-deps"
        )
        with patch("vip.auth.sync_playwright", return_value=pw):
            with pytest.raises(AuthConfigError, match=r"playwright install --with-deps chromium"):
                start_headless_auth(
                    connect_url="https://c.example.com",
                    username="user",
                    password="pass",
                )

    def test_unrelated_playwright_launch_error_propagates(self):
        """Launch errors that aren't missing-deps must not be rewritten."""
        from playwright.sync_api import Error as PlaywrightError

        pw = MagicMock()
        pw.start.return_value.chromium.launch.side_effect = PlaywrightError(
            "Browser closed unexpectedly"
        )
        with patch("vip.auth.sync_playwright", return_value=pw):
            with pytest.raises(PlaywrightError, match="Browser closed unexpectedly"):
                start_headless_auth(
                    connect_url="https://c.example.com",
                    username="user",
                    password="pass",
                )
