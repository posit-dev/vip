"""Tests for vip.auth module — headless auth validation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from vip.auth import (
    AuthConfigError,
    start_headless_auth,
)


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

    def test_invalid_totp_seed_raises_before_playwright(self, monkeypatch):
        """Bad VIP_TEST_TOTP_SECRET fails fast with a clear error."""
        monkeypatch.setenv("VIP_TEST_TOTP_SECRET", "not-valid-base32-!!!")

        # If validation runs late, sync_playwright would be called. Patch
        # it to blow up loudly so this test catches that regression.
        def boom(*a, **kw):
            raise AssertionError("Playwright launched despite invalid seed")

        monkeypatch.setattr("vip.auth.sync_playwright", boom)

        with pytest.raises(AuthConfigError, match="VIP_TEST_TOTP_SECRET"):
            start_headless_auth(
                connect_url="https://connect.example.com",
                idp="keycloak",
                provider="oidc",
                username="user",
                password="pass",
            )

    def test_valid_totp_seed_passes_validation(self, monkeypatch, tmp_path):
        """A valid seed must not block startup. Stub Playwright so the
        test asserts only that validation does not raise.
        """
        monkeypatch.setenv("VIP_TEST_TOTP_SECRET", "JBSWY3DPEHPK3PXP")

        # Stub Playwright so we can exercise validation without a browser.
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        pw = MagicMock()
        browser = pw.start.return_value.chromium.launch.return_value
        page = browser.new_context.return_value.new_page.return_value
        # Make goto time out so the call returns quickly via the existing
        # error path, without us needing to fake a full successful flow.
        page.goto.side_effect = PlaywrightTimeoutError("timed out")

        monkeypatch.setattr("vip.auth.sync_playwright", lambda: pw)

        # Should NOT raise an AuthConfigError mentioning the seed; the
        # timeout path is the expected failure here.
        with pytest.raises(AuthConfigError) as exc_info:
            start_headless_auth(
                connect_url="https://connect.example.com",
                idp="keycloak",
                provider="oidc",
                username="user",
                password="pass",
            )
        assert "VIP_TEST_TOTP_SECRET" not in str(exc_info.value)


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
        with (
            patch("vip.auth.sync_playwright", return_value=stub),
            pytest.raises(AuthConfigError, match="timed out"),
        ):
            start_headless_auth(
                connect_url="https://c.example.com",
                username="user",
                password="pass",
            )

    def test_playwright_error_during_login_becomes_auth_config_error(self):
        from playwright.sync_api import Error as PlaywrightError

        stub = self._make_playwright_stub(PlaywrightError("net::ERR_NAME_NOT_RESOLVED"))
        with (
            patch("vip.auth.sync_playwright", return_value=stub),
            pytest.raises(AuthConfigError, match="failed during login"),
        ):
            start_headless_auth(
                connect_url="https://c.example.com",
                username="user",
                password="pass",
            )

    def test_missing_chromium_system_deps_gives_remediation(self):
        """Missing host libraries at chromium launch must surface the
        ``vip install`` remediation command (see issue #169).
        """
        from playwright.sync_api import Error as PlaywrightError

        pw = MagicMock()
        pw.start.return_value.chromium.launch.side_effect = PlaywrightError(
            "Host system is missing dependencies to run browsers.\n"
            "Please install them with the following command:\n"
            "    sudo playwright install-deps"
        )
        with (
            patch("vip.auth.sync_playwright", return_value=pw),
            pytest.raises(AuthConfigError, match=r"vip install"),
        ):
            start_headless_auth(
                connect_url="https://c.example.com",
                username="user",
                password="pass",
            )

    def test_no_display_at_interactive_launch_gives_remediation(self):
        """A headed launch with no display (e.g. --interactive-auth run
        directly on a headless server) must point at --headless-auth instead
        of surfacing Playwright's raw XServer error (see issue #588).
        """
        from playwright.sync_api import Error as PlaywrightError

        from vip.auth import start_interactive_auth

        pw = MagicMock()
        pw.start.return_value.chromium.launch.side_effect = PlaywrightError(
            "Looks like you launched a headed browser without having a XServer "
            "running.\nSet either 'headless: true' or use 'xvfb-run "
            "<your-playwright-app>' before running Playwright."
        )
        with (
            patch("vip.auth.sync_playwright", return_value=pw),
            pytest.raises(AuthConfigError, match="--headless-auth"),
        ):
            start_interactive_auth(connect_url="https://c.example.com")

    def test_unrelated_playwright_launch_error_propagates(self):
        """Launch errors that aren't missing-deps must not be rewritten."""
        from playwright.sync_api import Error as PlaywrightError

        pw = MagicMock()
        pw.start.return_value.chromium.launch.side_effect = PlaywrightError(
            "Browser closed unexpectedly"
        )
        with (
            patch("vip.auth.sync_playwright", return_value=pw),
            pytest.raises(PlaywrightError, match="Browser closed unexpectedly"),
        ):
            start_headless_auth(
                connect_url="https://c.example.com",
                username="user",
                password="pass",
            )


class TestStartHeadlessAuthSchemeResolutionWiring:
    """Headless counterpart to TestStartInteractiveAuthSchemeResolutionWiring."""

    def _stub_headless_playwright(self, monkeypatch) -> None:
        pw = MagicMock()
        browser = pw.start.return_value.chromium.launch.return_value
        page = browser.new_context.return_value.new_page.return_value
        # ``_sanitize_url(page.url)`` is called unconditionally (its result
        # is only *printed* conditionally) and expects a real string.
        page.url = "https://connect.example.com/"
        monkeypatch.setattr("vip.auth.sync_playwright", lambda: pw)
        monkeypatch.setattr("vip.auth._fill_product_login", lambda *a, **kw: None)
        monkeypatch.setattr("vip.auth._wait_for_product_redirect", lambda *a, **kw: None)
        return page

    def test_inferred_scheme_is_resolved_before_use(self, monkeypatch):
        from vip.auth import start_headless_auth

        self._stub_headless_playwright(monkeypatch)
        monkeypatch.setattr("vip.auth._resolve_connect_api_base", lambda *a, **kw: a[0])
        mint = MagicMock(return_value="FAKE_KEY")
        monkeypatch.setattr("vip.auth._create_api_key_via_session", mint)
        resolve = MagicMock(return_value="http://connect.example.com")
        monkeypatch.setattr("vip.auth.resolve_url_scheme", resolve)

        session = start_headless_auth(
            connect_url="https://connect.example.com",
            username="user",
            password="pass",
            connect_url_scheme_inferred=True,
        )

        resolve.assert_called_once()
        called_pc = resolve.call_args.args[0]
        assert called_pc.url == "https://connect.example.com"
        assert called_pc.url_scheme_inferred is True
        assert resolve.call_args.kwargs == {"insecure": False, "ca_bundle": None, "proxy": None}
        assert session._connect_url == "http://connect.example.com"
        assert mint.call_args.args[1] == "http://connect.example.com"

    def test_explicit_scheme_never_probes(self, monkeypatch):
        """See the interactive-auth counterpart's docstring: resolve_url_scheme
        is always called, but must no-op on its own for an explicit scheme --
        proved here by mocking httpx.get (the real network boundary) rather
        than resolve_url_scheme itself.
        """
        from vip.auth import start_headless_auth

        self._stub_headless_playwright(monkeypatch)
        monkeypatch.setattr("vip.auth._resolve_connect_api_base", lambda *a, **kw: a[0])
        monkeypatch.setattr("vip.auth._create_api_key_via_session", lambda *a, **kw: "FAKE_KEY")

        with patch("httpx.get") as mock_get:
            session = start_headless_auth(
                connect_url="https://connect.example.com",
                username="user",
                password="pass",
                connect_url_scheme_inferred=False,
            )

        mock_get.assert_not_called()
        assert session._connect_url == "https://connect.example.com"


class TestHeadlessAuthTLSFlags:
    """start_headless_auth passes TLS config to browser.new_context()."""

    def _make_playwright_stub(self) -> MagicMock:
        """Stub sync_playwright() that raises PlaywrightTimeoutError on goto
        (so the test terminates quickly without completing auth).
        """
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        pw = MagicMock()
        browser = pw.start.return_value.chromium.launch.return_value
        page = browser.new_context.return_value.new_page.return_value
        page.goto.side_effect = PlaywrightTimeoutError("stub timeout")
        return pw

    def test_insecure_passes_ignore_https_errors(self):
        """insecure=True must call new_context(ignore_https_errors=True)."""
        stub = self._make_playwright_stub()
        browser = stub.start.return_value.chromium.launch.return_value

        with (
            patch("vip.auth.sync_playwright", return_value=stub),
            pytest.raises(AuthConfigError, match="timed out"),
        ):
            start_headless_auth(
                connect_url="https://c.example.com",
                username="user",
                password="pass",
                insecure=True,
            )

        browser.new_context.assert_called_once()
        kwargs = browser.new_context.call_args.kwargs
        assert kwargs.get("ignore_https_errors") is True

    def test_no_insecure_does_not_set_ignore_https_errors(self):
        """Without insecure, new_context must receive ignore_https_errors=False."""
        stub = self._make_playwright_stub()
        browser = stub.start.return_value.chromium.launch.return_value

        with (
            patch("vip.auth.sync_playwright", return_value=stub),
            pytest.raises(AuthConfigError, match="timed out"),
        ):
            start_headless_auth(
                connect_url="https://c.example.com",
                username="user",
                password="pass",
                insecure=False,
            )

        browser.new_context.assert_called_once()
        kwargs = browser.new_context.call_args.kwargs
        assert kwargs.get("ignore_https_errors") is False

    def test_ca_bundle_sets_node_extra_ca_certs(self, tmp_path, monkeypatch):
        """ca_bundle must set NODE_EXTRA_CA_CERTS before sync_playwright().start()."""
        import os
        from pathlib import Path

        ca_file = tmp_path / "ca.pem"
        ca_file.write_text("# fake CA")

        stub = self._make_playwright_stub()
        captured: list[str | None] = []

        original_start = stub.start

        def capturing_start():
            captured.append(os.environ.get("NODE_EXTRA_CA_CERTS"))
            return original_start()

        stub.start = capturing_start

        monkeypatch.delenv("NODE_EXTRA_CA_CERTS", raising=False)

        with (
            patch("vip.auth.sync_playwright", return_value=stub),
            pytest.raises(AuthConfigError, match="timed out"),
        ):
            start_headless_auth(
                connect_url="https://c.example.com",
                username="user",
                password="pass",
                ca_bundle=Path(ca_file),
            )

        assert len(captured) == 1
        assert captured[0] == str(ca_file)
        # Verify env is restored after the call
        assert os.environ.get("NODE_EXTRA_CA_CERTS") is None

    def test_ca_bundle_env_restored_after_call(self, tmp_path, monkeypatch):
        """NODE_EXTRA_CA_CERTS must be restored to its prior value after auth."""
        import os
        from pathlib import Path

        ca_file = tmp_path / "ca.pem"
        ca_file.write_text("# fake CA")
        prev_value = "/prior/ca.pem"
        monkeypatch.setenv("NODE_EXTRA_CA_CERTS", prev_value)

        stub = self._make_playwright_stub()

        with (
            patch("vip.auth.sync_playwright", return_value=stub),
            pytest.raises(AuthConfigError, match="timed out"),
        ):
            start_headless_auth(
                connect_url="https://c.example.com",
                username="user",
                password="pass",
                ca_bundle=Path(ca_file),
            )

        assert os.environ.get("NODE_EXTRA_CA_CERTS") == prev_value
