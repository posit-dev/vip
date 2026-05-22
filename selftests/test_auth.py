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
        test asserts only that validation does not raise."""
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
        ``vip install`` remediation command (see issue #169)."""
        from playwright.sync_api import Error as PlaywrightError

        pw = MagicMock()
        pw.start.return_value.chromium.launch.side_effect = PlaywrightError(
            "Host system is missing dependencies to run browsers.\n"
            "Please install them with the following command:\n"
            "    sudo playwright install-deps"
        )
        with patch("vip.auth.sync_playwright", return_value=pw):
            with pytest.raises(AuthConfigError, match=r"vip install"):
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


class TestSaveAuthCache:
    """_save_auth_cache must not poison the cache with failed mint attempts.

    When Connect is configured but key minting failed, api_key is None.
    Caching that state means subsequent runs short-circuit via the cache
    and never re-attempt the mint — the specific warning explaining why
    it failed is lost, and the user sees an opaque "set VIP_CONNECT_API_KEY"
    warning for 4 hours."""

    def _make_session(self, tmp_path, *, connect_url: str, api_key: str | None):
        from vip.auth import InteractiveAuthSession

        state = tmp_path / "state.json"
        state.write_text('{"cookies": []}')
        return InteractiveAuthSession(
            storage_state_path=state,
            api_key=api_key,
            key_name="_vip_interactive_123",
            _connect_url=connect_url,
        )

    def test_skips_cache_when_connect_configured_but_mint_failed(self, tmp_path):
        from vip.auth import _save_auth_cache

        session = self._make_session(tmp_path, connect_url="https://c.example.com", api_key=None)
        cache = tmp_path / ".vip-auth-cache.json"

        _save_auth_cache(session, cache)

        assert not cache.exists(), "cache must not be written when mint failed"
        assert not cache.with_suffix(".meta.json").exists()

    def test_writes_cache_on_successful_mint(self, tmp_path):
        from vip.auth import _save_auth_cache

        session = self._make_session(
            tmp_path, connect_url="https://c.example.com", api_key="REAL_KEY"
        )
        cache = tmp_path / ".vip-auth-cache.json"

        _save_auth_cache(session, cache)

        assert cache.exists()
        meta = cache.with_suffix(".meta.json")
        import json

        assert json.loads(meta.read_text())["api_key"] == "REAL_KEY"

    def test_writes_cache_when_connect_not_configured(self, tmp_path):
        """Workbench-only flows: api_key=None is legitimate, cache storage state."""
        from vip.auth import _save_auth_cache

        session = self._make_session(tmp_path, connect_url="", api_key=None)
        cache = tmp_path / ".vip-auth-cache.json"

        _save_auth_cache(session, cache)

        assert cache.exists()


class TestInteractiveAuthSessionCleanup:
    """Cleanup must not delete an API key that the on-disk cache still
    references.  Otherwise run 1 mints K, writes cache(K), then deletes
    K at cleanup — run 2 loads cache(K), tries to authenticate, 401s.
    Orphan cleanup at the next mint (via ``_delete_stale_vip_keys``)
    reaps keys older than :data:`_ORPHAN_MIN_AGE_SECONDS`.
    """

    def _session_with_cache(self, tmp_path, *, api_key: str, cache_key: str | None):
        """Return a session whose ``_cache_path`` points at a cache whose
        meta.json holds ``cache_key`` (or no cache file at all if None)."""
        import json

        from vip.auth import InteractiveAuthSession

        state = tmp_path / "state.json"
        state.write_text('{"cookies": []}')
        cache = tmp_path / ".vip-auth-cache.json"
        if cache_key is not None:
            cache.write_text('{"cookies": []}')
            cache.with_suffix(".meta.json").write_text(
                json.dumps({"api_key": cache_key, "key_name": "_vip_interactive_1"})
            )
        return (
            InteractiveAuthSession(
                storage_state_path=state,
                api_key=api_key,
                key_name="_vip_interactive_1",
                _connect_url="https://c.example.com",
                _cache_path=cache,
            ),
            cache,
        )

    def test_skips_delete_when_cache_still_references_the_key(self, tmp_path):
        """Happy path: cache.meta.api_key == session.api_key → don't delete.
        Next run will cache-hit and reuse the same key successfully."""
        session, _ = self._session_with_cache(tmp_path, api_key="LIVE", cache_key="LIVE")

        with patch("vip.auth._delete_api_key") as deleter:
            session.cleanup()

        deleter.assert_not_called()

    def test_deletes_when_cache_file_is_missing(self, tmp_path):
        """No cache on disk → no future run will reference this key → delete it
        now so we don't leave orphans accumulating between mint-time cleanups."""
        session, _ = self._session_with_cache(tmp_path, api_key="LIVE", cache_key=None)

        with patch("vip.auth._delete_api_key") as deleter:
            session.cleanup()

        deleter.assert_called_once_with(
            "https://c.example.com", "LIVE", "_vip_interactive_1", insecure=False, ca_bundle=None
        )

    def test_deletes_when_cache_state_file_is_missing(self, tmp_path):
        """Meta without state is stale metadata — there is no cache the next
        run could actually load from, so our key is not reachable by
        future runs.  Delete it now so it doesn't orphan until the next
        mint sweeps stale keys."""
        import json

        from vip.auth import InteractiveAuthSession

        state = tmp_path / "state.json"
        state.write_text('{"cookies": []}')
        cache = tmp_path / ".vip-auth-cache.json"
        # Meta exists and references our key, but the cache state file was
        # removed (disk pressure, manual cleanup, etc.).
        cache.with_suffix(".meta.json").write_text(
            json.dumps({"api_key": "LIVE", "key_name": "_vip_interactive_1"})
        )
        assert not cache.exists()

        session = InteractiveAuthSession(
            storage_state_path=state,
            api_key="LIVE",
            key_name="_vip_interactive_1",
            _connect_url="https://c.example.com",
            _cache_path=cache,
        )

        with patch("vip.auth._delete_api_key") as deleter:
            session.cleanup()

        deleter.assert_called_once_with(
            "https://c.example.com", "LIVE", "_vip_interactive_1", insecure=False, ca_bundle=None
        )

    def test_deletes_when_cache_state_file_is_malformed(self, tmp_path):
        """A corrupted cache state file is unusable — Playwright will fail to
        load it, so the next run won't actually reuse our key.  Treat the
        cache as unreachable and delete the key now rather than leaving
        an orphan until the next mint-time sweep."""
        import json

        from vip.auth import InteractiveAuthSession

        cache = tmp_path / ".vip-auth-cache.json"
        cache.write_text("{not valid json")
        cache.with_suffix(".meta.json").write_text(
            json.dumps({"api_key": "LIVE", "key_name": "_vip_interactive_1"})
        )

        session = InteractiveAuthSession(
            storage_state_path=cache,
            api_key="LIVE",
            key_name="_vip_interactive_1",
            _connect_url="https://c.example.com",
            _cache_path=cache,
        )

        with patch("vip.auth._delete_api_key") as deleter:
            session.cleanup()

        deleter.assert_called_once_with(
            "https://c.example.com", "LIVE", "_vip_interactive_1", insecure=False, ca_bundle=None
        )

    def test_deletes_when_cache_references_a_different_key(self, tmp_path):
        """Concurrent run overwrote the cache with its own key → our key is
        no longer referenced and should be deleted so it doesn't linger."""
        session, _ = self._session_with_cache(tmp_path, api_key="MINE", cache_key="OTHER")

        with patch("vip.auth._delete_api_key") as deleter:
            session.cleanup()

        deleter.assert_called_once_with(
            "https://c.example.com", "MINE", "_vip_interactive_1", insecure=False, ca_bundle=None
        )

    def test_deletes_when_session_has_no_cache_path(self, tmp_path):
        """Sessions created outside the caching flow (``_cache_path`` unset)
        behave like before: delete on cleanup."""
        from vip.auth import InteractiveAuthSession

        state = tmp_path / "state.json"
        state.write_text('{"cookies": []}')
        session = InteractiveAuthSession(
            storage_state_path=state,
            api_key="LIVE",
            key_name="_vip_interactive_1",
            _connect_url="https://c.example.com",
        )

        with patch("vip.auth._delete_api_key") as deleter:
            session.cleanup()

        deleter.assert_called_once_with(
            "https://c.example.com", "LIVE", "_vip_interactive_1", insecure=False, ca_bundle=None
        )


class TestAuthenticateWorkbench:
    """_authenticate_workbench establishes the Workbench SSO session after
    Connect auth has already succeeded.  Network failures here must NOT
    crash the pytest session — Connect tests should still run.  The
    helper returns ``None`` on success or a short failure reason that
    callers stash on :class:`InteractiveAuthSession` so test-time skip
    messages can quote the underlying cause."""

    def test_playwright_error_on_goto_is_non_fatal(self, capsys):
        """A PlaywrightError from page.goto() (e.g. ERR_CONNECTION_REFUSED,
        redirect-to-http) must be caught, logged as a warning, and return
        a failure reason.  Otherwise the whole pytest session dies with
        INTERNALERROR.  See issue #171."""
        from playwright.sync_api import Error as PlaywrightError

        from vip.auth import _authenticate_workbench

        page = MagicMock()
        page.goto.side_effect = PlaywrightError(
            "net::ERR_CONNECTION_REFUSED at https://wb.example.com/pwb"
        )

        result = _authenticate_workbench(page, "https://wb.example.com/pwb")

        out = capsys.readouterr().out
        assert "Could not reach Workbench" in out
        assert "https://wb.example.com/pwb" in out
        assert result is not None
        assert "could not reach Workbench" in result
        assert "https://wb.example.com/pwb" in result

    def test_returns_none_when_landed_on_dashboard(self):
        """SSO completed and the page is on the Workbench dashboard → success.
        The helper must return ``None`` so the caller doesn't stash a
        bogus error on the session."""
        from unittest.mock import PropertyMock

        from vip.auth import _authenticate_workbench

        page = MagicMock()
        page.goto.return_value = None
        page.wait_for_load_state.return_value = None
        type(page).url = PropertyMock(return_value="https://wb.example.com/")

        result = _authenticate_workbench(page, "https://wb.example.com")

        assert result is None

    def test_returns_reason_when_timeout_keeps_us_on_login(self, monkeypatch):
        """If the 2-minute redirect poll expires while we're still on
        /auth-sign-in, the helper must return a string explaining why so
        the workbench fixture can surface it instead of guessing."""
        from unittest.mock import PropertyMock

        from vip import auth as auth_mod

        page = MagicMock()
        page.goto.return_value = None
        page.wait_for_load_state.return_value = None
        type(page).url = PropertyMock(return_value="https://wb.example.com/auth-sign-in")

        # Force the deadline loop to exit immediately so the test finishes fast.
        times = iter([0.0, 1000.0])
        monkeypatch.setattr(auth_mod.time, "monotonic", lambda: next(times))

        result = auth_mod._authenticate_workbench(page, "https://wb.example.com")

        assert result is not None
        assert "did not complete" in result
        assert "auth-sign-in" in result


class TestLoadCachedAuth:
    """_load_cached_auth must refuse to reuse a cache that was minted
    against different product URLs.  The cache file lives one-per-
    checkout-directory, so reusing it across sites would silently send
    the wrong session cookies (and API key) to the new target."""

    @staticmethod
    def _write_cache(tmp_path, *, connect_url: str, workbench_url: str = ""):
        import json
        from pathlib import Path as _Path

        cache = _Path(tmp_path) / ".vip-auth-cache.json"
        cache.write_text('{"cookies": []}')
        cache.with_suffix(".meta.json").write_text(
            json.dumps(
                {
                    "api_key": "CACHED",
                    "key_name": "_vip_interactive_1",
                    "connect_url": connect_url,
                    "workbench_url": workbench_url,
                }
            )
        )
        return cache

    def test_reuses_cache_when_urls_match(self, tmp_path):
        from vip.auth import _load_cached_auth

        cache = self._write_cache(
            tmp_path, connect_url="https://c.example.com", workbench_url="https://w.example.com"
        )

        session = _load_cached_auth(
            cache,
            requested_connect_url="https://c.example.com",
            requested_workbench_url="https://w.example.com",
        )

        assert session is not None
        assert session.api_key == "CACHED"

    def test_rejects_cache_when_connect_url_differs(self, tmp_path, capsys):
        from vip.auth import _load_cached_auth

        cache = self._write_cache(tmp_path, connect_url="https://site-a.example.com")

        session = _load_cached_auth(
            cache,
            requested_connect_url="https://site-b.example.com",
            requested_workbench_url=None,
        )

        assert session is None
        assert "Ignoring cached auth session" in capsys.readouterr().out

    def test_rejects_cache_when_workbench_was_not_recorded(self, tmp_path):
        """A cache minted with only Connect lacks Workbench cookies; a
        later run that now also wants Workbench would skip every
        Workbench test on stale state.  Treat as a miss."""
        from vip.auth import _load_cached_auth

        cache = self._write_cache(tmp_path, connect_url="https://c.example.com")

        session = _load_cached_auth(
            cache,
            requested_connect_url="https://c.example.com",
            requested_workbench_url="https://w.example.com",
        )

        assert session is None

    def test_url_match_normalizes_host_case_and_trailing_slash(self, tmp_path):
        """Scheme and netloc are case-insensitive per RFC 3986 and a
        single trailing slash on the path is not meaningful, so these
        must still hit the cache."""
        from vip.auth import _load_cached_auth

        cache = self._write_cache(
            tmp_path,
            connect_url="https://Connect.Example.COM/",
            workbench_url="https://wb.example.com",
        )

        session = _load_cached_auth(
            cache,
            requested_connect_url="https://connect.example.com",
            requested_workbench_url="https://wb.example.com/",
        )

        assert session is not None

    def test_url_match_preserves_path_case(self, tmp_path):
        """URL paths are case-sensitive: ``/Dashboard`` and ``/dashboard``
        can resolve to different Connect deployments when a sub-path
        mount is used.  Lowercasing the path (the prior behaviour) would
        send stale storage state and API key to the wrong target."""
        from vip.auth import _load_cached_auth

        cache = self._write_cache(
            tmp_path,
            connect_url="https://connect.example.com/Dashboard",
        )

        session = _load_cached_auth(
            cache,
            requested_connect_url="https://connect.example.com/dashboard",
            requested_workbench_url=None,
        )

        assert session is None


class TestWaitForProductRedirect:
    """_wait_for_product_redirect handles the Workbench OIDC confirmation page.

    After the IdP round-trip, Workbench shows a form with a "Sign in with
    OpenID" button that must be clicked to complete the session.  Headed
    flows rely on the user; headless flows must click it automatically.
    """

    @staticmethod
    def _page_with_urls(urls: list[str], *, oidc_button_visible: bool) -> MagicMock:
        """Stub a Page whose ``url`` returns each value in *urls* in order,
        repeating the last value once the list is exhausted."""
        from unittest.mock import PropertyMock

        page = MagicMock()
        type(page).url = PropertyMock(
            side_effect=lambda urls=list(urls): urls.pop(0) if len(urls) > 1 else urls[0]
        )
        btn = MagicMock()
        btn.count.return_value = 1 if oidc_button_visible else 0
        btn.first.is_visible.return_value = oidc_button_visible
        page.locator.return_value = btn
        return page

    def test_clicks_oidc_confirm_button_once(self):
        """When the Workbench OIDC confirmation page is up, click the
        button and stop polling once the URL settles on the dashboard."""
        from vip.auth import _wait_for_product_redirect

        page = self._page_with_urls(
            [
                "https://wb.example.com/auth-sign-in?appUri=/",
                "https://wb.example.com/auth-sign-in?appUri=/",
                "https://wb.example.com/",
            ],
            oidc_button_visible=True,
        )

        _wait_for_product_redirect(page, "https://wb.example.com")

        page.locator.assert_called_with("form[action='auth-openid-sign-in'] #signinbutton")
        page.locator.return_value.first.click.assert_called_once()

    def test_does_not_click_when_button_absent(self):
        """If we land directly on the dashboard, the helper must not
        try to click anything."""
        from vip.auth import _wait_for_product_redirect

        page = self._page_with_urls(
            ["https://wb.example.com/"],
            oidc_button_visible=False,
        )

        _wait_for_product_redirect(page, "https://wb.example.com")

        page.locator.return_value.first.click.assert_not_called()


class TestClickWorkbenchOidcConfirm:
    """_click_workbench_oidc_confirm targets the specific Workbench form
    (``action='auth-openid-sign-in'``) so unrelated submit buttons on
    other login pages are not clicked by accident."""

    def test_clicks_when_button_visible(self):
        from vip.auth import _click_workbench_oidc_confirm

        page = MagicMock()
        btn = page.locator.return_value
        btn.count.return_value = 1
        btn.first.is_visible.return_value = True

        assert _click_workbench_oidc_confirm(page) is True
        btn.first.click.assert_called_once()

    def test_returns_false_when_button_missing(self):
        from vip.auth import _click_workbench_oidc_confirm

        page = MagicMock()
        page.locator.return_value.count.return_value = 0

        assert _click_workbench_oidc_confirm(page) is False
        page.locator.return_value.first.click.assert_not_called()

    def test_returns_false_when_button_not_visible(self):
        from vip.auth import _click_workbench_oidc_confirm

        page = MagicMock()
        btn = page.locator.return_value
        btn.count.return_value = 1
        btn.first.is_visible.return_value = False

        assert _click_workbench_oidc_confirm(page) is False
        btn.first.click.assert_not_called()

    def test_swallows_playwright_error(self):
        """Transient Playwright errors during the lookup must not crash
        the surrounding wait loop."""
        from playwright.sync_api import Error as PlaywrightError

        from vip.auth import _click_workbench_oidc_confirm

        page = MagicMock()
        page.locator.side_effect = PlaywrightError("locator failed")

        assert _click_workbench_oidc_confirm(page) is False


class TestHttpxVerify:
    """_httpx_verify derives the httpx ``verify`` value from TLS config params.

    This is the single source of truth for the verify plumbing used by
    _create_api_key_via_session and _delete_api_key (the latter already had
    an inline equivalent; both now delegate to this helper).
    """

    def test_insecure_true_returns_false(self):
        from vip.auth import _httpx_verify

        assert _httpx_verify(True, None) is False

    def test_ca_bundle_returns_str_path(self, tmp_path):
        from vip.auth import _httpx_verify

        ca = tmp_path / "ca.pem"
        assert _httpx_verify(False, ca) == str(ca)

    def test_defaults_return_true(self):
        from vip.auth import _httpx_verify

        assert _httpx_verify(False, None) is True

    def test_insecure_wins_over_ca_bundle(self, tmp_path):
        """When both insecure=True and a ca_bundle path are provided,
        insecure wins — mirrors cli.py:391 logic."""
        from vip.auth import _httpx_verify

        ca = tmp_path / "ca.pem"
        assert _httpx_verify(True, ca) is False


class TestResolveConnectApiBase:
    """_resolve_connect_api_base handles split layouts where the Connect
    dashboard sits on a sub-path (``/connect/``) but the API stays at the
    host root.  ``<connect_url>/__api__/server_settings`` then 404s while
    ``<host>/__api__/server_settings`` returns 200 with a
    ``dashboard_path`` matching the sub-path.
    """

    @staticmethod
    def _resp(status_code: int, *, json_data=None, content_type: str = "application/json"):
        resp = MagicMock()
        resp.status_code = status_code
        resp.headers = {"content-type": content_type}
        resp.json.return_value = json_data if json_data is not None else {}
        return resp

    def test_root_url_returned_as_is(self):
        """When connect_url has no sub-path there's nothing to fall back to —
        skip the probe entirely."""
        from vip.auth import _resolve_connect_api_base

        with patch("httpx.get") as mock_get:
            result = _resolve_connect_api_base("https://connect.example.com")

        assert result == "https://connect.example.com"
        mock_get.assert_not_called()

    def test_primary_200_keeps_url(self):
        """Standard layout: ``<connect_url>/__api__/`` answers 200 → keep it."""
        from vip.auth import _resolve_connect_api_base

        with patch("httpx.get", return_value=self._resp(200, json_data={})):
            result = _resolve_connect_api_base("https://connect.example.com/connect")

        assert result == "https://connect.example.com/connect"

    def test_split_layout_switches_to_root(self):
        """Sub-path dashboard + root API → return the host root."""
        from vip.auth import _resolve_connect_api_base

        responses = [
            self._resp(404, content_type="text/plain"),
            self._resp(200, json_data={"dashboard_path": "/connect"}),
        ]
        with patch("httpx.get", side_effect=responses):
            result = _resolve_connect_api_base("https://connect.example.com/connect/")

        assert result == "https://connect.example.com"

    def test_dashboard_path_mismatch_keeps_url(self):
        """Root API returns 200 but its dashboard_path is for a different
        product — refuse to switch."""
        from vip.auth import _resolve_connect_api_base

        responses = [
            self._resp(404),
            self._resp(200, json_data={"dashboard_path": "/somethingelse"}),
        ]
        with patch("httpx.get", side_effect=responses):
            result = _resolve_connect_api_base("https://connect.example.com/connect")

        assert result == "https://connect.example.com/connect"

    def test_missing_dashboard_path_keeps_url(self):
        """Root /__api__/server_settings returns 200 JSON but has no
        ``dashboard_path`` field — unverified.  Keep the original URL
        rather than risking a false-positive rewrite to a sibling
        endpoint that just happens to answer JSON 200."""
        from vip.auth import _resolve_connect_api_base

        responses = [
            self._resp(404),
            self._resp(200, json_data={"hostname": "ambiguous"}),
        ]
        with patch("httpx.get", side_effect=responses):
            result = _resolve_connect_api_base("https://connect.example.com/connect")

        assert result == "https://connect.example.com/connect"

    @pytest.mark.parametrize("payload", [[], [1, 2, 3], "string", 42, None])
    def test_non_dict_json_keeps_url(self, payload):
        """Root /__api__/server_settings returns a valid JSON 200 that
        isn't an object (list, scalar, null) — calling ``.get()`` on it
        would raise ``AttributeError``.  The resolver must treat this as
        ambiguous and keep the original URL."""
        from vip.auth import _resolve_connect_api_base

        responses = [
            self._resp(404),
            self._resp(200, json_data=payload),
        ]
        with patch("httpx.get", side_effect=responses):
            result = _resolve_connect_api_base("https://connect.example.com/connect")

        assert result == "https://connect.example.com/connect"

    def test_secondary_non_json_keeps_url(self):
        """Root /__api__/server_settings returns 200 but HTML — not Connect.
        Refuse to switch."""
        from vip.auth import _resolve_connect_api_base

        responses = [
            self._resp(404),
            self._resp(200, content_type="text/html"),
        ]
        with patch("httpx.get", side_effect=responses):
            result = _resolve_connect_api_base("https://connect.example.com/connect")

        assert result == "https://connect.example.com/connect"

    def test_both_404_returns_original(self):
        """Both probes 404 → leave URL alone; existing mint diagnostics will
        guide the user."""
        from vip.auth import _resolve_connect_api_base

        responses = [self._resp(404), self._resp(404)]
        with patch("httpx.get", side_effect=responses):
            result = _resolve_connect_api_base("https://connect.example.com/connect")

        assert result == "https://connect.example.com/connect"

    def test_transport_error_returns_original(self):
        """httpx.HTTPError on the probe must not crash auth setup."""
        import httpx

        from vip.auth import _resolve_connect_api_base

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")):
            result = _resolve_connect_api_base("https://connect.example.com/connect")

        assert result == "https://connect.example.com/connect"


class TestCreateApiKeyViaSession:
    """_create_api_key_via_session uses httpx + cookies extracted from the
    browser session so that ``insecure`` / ``ca_bundle`` TLS settings are
    honoured (issue #239).  All HTTP calls go through an ``httpx.Client``
    constructed with the verify value derived from those parameters, not
    through Playwright's ``APIRequestContext`` which has no verify equivalent.

    Note on end-to-end coverage: these selftests confirm the plumbing shape
    (correct verify value, correct cookie/header forwarding, correct orphan-key
    logic).  Verifying that ``--insecure`` actually suppresses
    ``CERTIFICATE_VERIFY_FAILED`` against a real self-signed Connect deployment
    requires a manual test; @samcofer should validate before merge per the plan.
    """

    @staticmethod
    def _httpx_response(
        *,
        is_success: bool = True,
        status_code: int = 200,
        json_data=None,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> MagicMock:
        """Stub an httpx Response with the given shape."""
        resp = MagicMock()
        resp.is_success = is_success
        resp.status_code = status_code
        resp.json.return_value = json_data if json_data is not None else {}
        resp.text = text
        # Real dict so ``headers.get("content-type", ...)`` returns a string,
        # not a MagicMock (which would make diagnostic output unreadable).
        resp.headers = headers if headers is not None else {}
        return resp

    @staticmethod
    def _page(cookies: list[dict] | None = None) -> MagicMock:
        """Stub a Playwright Page with a cookie jar pre-populated.

        Defaults to a jar containing an ``HttpOnly`` RSC-XSRF cookie —
        that's how Connect actually sets the token, which is why the
        implementation reads via ``page.context.cookies()`` rather than
        ``document.cookie``.
        """
        if cookies is None:
            cookies = [{"name": "RSC-XSRF", "value": "x", "httpOnly": True}]
        page = MagicMock()
        page.context.cookies.return_value = cookies
        return page

    def _patch_httpx_client(self, get_side_effect=None, post_rv=None, delete_side_effect=None):
        """Return a context manager that patches httpx.Client with a stub.

        The stub's ``__enter__`` returns a mock client whose ``.get()``,
        ``.post()``, and ``.delete()`` are pre-configured.

        ``_create_api_key_via_session`` does ``import httpx`` locally inside
        the function, so the import is bound to the ``httpx`` module in
        ``sys.modules`` at call time.  Patching ``httpx.Client`` directly
        intercepts it regardless of where the import happens.
        """
        client_mock = MagicMock()
        if get_side_effect is not None:
            client_mock.get.side_effect = get_side_effect
        if post_rv is not None:
            client_mock.post.return_value = post_rv
        if delete_side_effect is not None:
            client_mock.delete.side_effect = delete_side_effect
        # httpx.Client is used as a context manager (``with httpx.Client(...) as c``).
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=client_mock)
        cm.__exit__ = MagicMock(return_value=False)
        client_cls = MagicMock(return_value=cm)
        return patch("httpx.Client", client_cls), client_cls, client_mock

    def test_happy_path_creates_key_and_sends_xsrf(self):
        """List is empty (no orphans), POST returns a key string.
        The httpx Client must be constructed with the XSRF header and
        cookies extracted from the browser session."""
        from vip.auth import _create_api_key_via_session

        page = self._page(
            [
                {"name": "RSC-XSRF", "value": "xsrf-token", "httpOnly": True},
                {"name": "connect-session", "value": "sess-123", "httpOnly": True},
            ]
        )

        me = self._httpx_response(json_data={"guid": "user-guid-abc"})
        keys_list = self._httpx_response(json_data=[])
        created = self._httpx_response(
            json_data={"id": "7", "name": "_vip_interactive_1", "key": "SECRETKEY" * 3}
        )

        def get_side_effect(path, **_kwargs):
            return me if path.endswith("/v1/user") else keys_list

        patcher, client_cls, client_mock = self._patch_httpx_client(
            get_side_effect=get_side_effect,
            post_rv=created,
        )
        with patcher:
            result = _create_api_key_via_session(
                page, "https://connect.example.com", "_vip_interactive_1"
            )

        assert result == "SECRETKEY" * 3

        # httpx.Client must be constructed with the XSRF header and cookies.
        init_kwargs = client_cls.call_args.kwargs
        assert init_kwargs["headers"] == {"X-Rsc-Xsrf": "xsrf-token"}
        assert init_kwargs["cookies"]["RSC-XSRF"] == "xsrf-token"
        assert init_kwargs["cookies"]["connect-session"] == "sess-123"

        # POST must include the key name as a JSON body — Connect's API
        # rejects form-encoded payloads with HTTP 400 "request JSON cannot
        # be parsed".
        post_call = client_mock.post.call_args
        assert post_call.args[0].endswith("/v1/users/user-guid-abc/keys")
        assert post_call.kwargs["json"] == {"name": "_vip_interactive_1"}
        assert "data" not in post_call.kwargs

    def test_insecure_flag_sets_verify_false(self):
        """When insecure=True, httpx.Client must be constructed with verify=False."""
        from vip.auth import _create_api_key_via_session

        page = self._page()
        me = self._httpx_response(json_data={"guid": "g"})
        keys_list = self._httpx_response(json_data=[])
        created = self._httpx_response(json_data={"id": "1", "key": "K" * 30})

        def get_side_effect(path, **_kw):
            return me if path.endswith("/v1/user") else keys_list

        patcher, client_cls, _client = self._patch_httpx_client(
            get_side_effect=get_side_effect,
            post_rv=created,
        )
        with patcher:
            result = _create_api_key_via_session(page, "https://c.example.com", "k", insecure=True)

        assert result == "K" * 30
        assert client_cls.call_args.kwargs["verify"] is False

    def test_ca_bundle_sets_verify_path(self, tmp_path):
        """When ca_bundle is set, httpx.Client must receive verify=str(ca_bundle)."""
        from vip.auth import _create_api_key_via_session

        ca = tmp_path / "ca.pem"
        page = self._page()
        me = self._httpx_response(json_data={"guid": "g"})
        keys_list = self._httpx_response(json_data=[])
        created = self._httpx_response(json_data={"id": "1", "key": "K" * 30})

        def get_side_effect(path, **_kw):
            return me if path.endswith("/v1/user") else keys_list

        patcher, client_cls, _client = self._patch_httpx_client(
            get_side_effect=get_side_effect,
            post_rv=created,
        )
        with patcher:
            result = _create_api_key_via_session(page, "https://c.example.com", "k", ca_bundle=ca)

        assert result == "K" * 30
        assert client_cls.call_args.kwargs["verify"] == str(ca)

    def test_deletes_orphan_vip_keys_before_creating(self):
        """Old _vip_interactive_<ts> keys must be deleted before the POST."""
        import time

        from vip.auth import _create_api_key_via_session

        old_ts = int(time.time()) - 7200
        call_order: list[tuple[str, str | None]] = []

        page = self._page()
        me = self._httpx_response(json_data={"guid": "g"})
        keys_list = self._httpx_response(
            json_data=[
                {"id": "1", "name": f"_vip_interactive_{old_ts}"},
                {"id": "2", "name": "my-personal-key"},
                {"id": "3", "name": f"_vip_interactive_{old_ts - 100}"},
            ]
        )

        def get_side_effect(path, **_kw):
            return me if path.endswith("/v1/user") else keys_list

        def delete_side_effect(path, **_kw):
            call_order.append(("DELETE", path.rsplit("/", 1)[-1]))
            return self._httpx_response(status_code=204)

        def post_side_effect(path, **_kw):
            call_order.append(("POST", None))
            return self._httpx_response(json_data={"id": "9", "key": "NEWKEY" * 5})

        patcher, _cls, client_mock = self._patch_httpx_client(
            get_side_effect=get_side_effect,
            delete_side_effect=delete_side_effect,
        )
        client_mock.post.side_effect = post_side_effect

        with patcher:
            result = _create_api_key_via_session(
                page, "https://c.example.com", "_vip_interactive_new"
            )

        assert result == "NEWKEY" * 5

        deleted_ids = [kid for (op, kid) in call_order if op == "DELETE"]
        assert sorted(deleted_ids) == ["1", "3"]

        # All DELETEs must come strictly before the POST.
        post_index = next(i for i, (op, _) in enumerate(call_order) if op == "POST")
        assert all(op == "DELETE" for op, _ in call_order[:post_index])
        assert post_index == len(call_order) - 1  # POST is last, ran once

    def test_skips_recent_orphan_keys(self):
        """Keys younger than _ORPHAN_MIN_AGE_SECONDS must NOT be deleted."""
        import time

        from vip.auth import _create_api_key_via_session

        recent_ts = int(time.time()) - 60

        page = self._page()
        me = self._httpx_response(json_data={"guid": "g"})
        keys_list = self._httpx_response(
            json_data=[{"id": "42", "name": f"_vip_interactive_{recent_ts}"}]
        )
        created = self._httpx_response(json_data={"id": "9", "key": "K" * 30})

        def get_side_effect(path, **_kw):
            return me if path.endswith("/v1/user") else keys_list

        patcher, _cls, client_mock = self._patch_httpx_client(
            get_side_effect=get_side_effect,
            post_rv=created,
        )
        with patcher:
            result = _create_api_key_via_session(
                page, "https://c.example.com", "_vip_interactive_new"
            )

        assert result == "K" * 30
        client_mock.delete.assert_not_called()

    def test_xsrf_falls_back_to_legacy_cookie_name(self):
        """Servers in legacy cookie mode set ``RSC-XSRF-legacy`` instead of
        ``RSC-XSRF``.  The implementation must fall back to the legacy name
        so Connect does not reject with ``HTTP 403 XSRF token mismatch``."""
        from vip.auth import _create_api_key_via_session

        page = self._page(
            [
                {"name": "RSC-XSRF-legacy", "value": "legacy-tok"},
                {"name": "rsconnect-legacy", "value": "sess", "httpOnly": True},
            ]
        )

        me = self._httpx_response(json_data={"guid": "g"})
        keys_list = self._httpx_response(json_data=[])
        created = self._httpx_response(json_data={"id": "1", "key": "K" * 30})

        def get_side_effect(path, **_kw):
            return me if path.endswith("/v1/user") else keys_list

        patcher, client_cls, _client = self._patch_httpx_client(
            get_side_effect=get_side_effect,
            post_rv=created,
        )
        with patcher:
            result = _create_api_key_via_session(page, "https://c.example.com", "k")

        assert result == "K" * 30
        assert client_cls.call_args.kwargs["headers"] == {"X-Rsc-Xsrf": "legacy-tok"}

    def test_xsrf_prefers_modern_name_when_both_present(self):
        """When both RSC-XSRF and RSC-XSRF-legacy are set, use the modern name."""
        from vip.auth import _create_api_key_via_session

        page = self._page(
            [
                {"name": "RSC-XSRF", "value": "new-tok"},
                {"name": "RSC-XSRF-legacy", "value": "old-tok"},
            ]
        )

        me = self._httpx_response(json_data={"guid": "g"})
        keys_list = self._httpx_response(json_data=[])
        created = self._httpx_response(json_data={"id": "1", "key": "K" * 30})

        def get_side_effect(path, **_kw):
            return me if path.endswith("/v1/user") else keys_list

        patcher, client_cls, _client = self._patch_httpx_client(
            get_side_effect=get_side_effect,
            post_rv=created,
        )
        with patcher:
            _create_api_key_via_session(page, "https://c.example.com", "k")

        assert client_cls.call_args.kwargs["headers"] == {"X-Rsc-Xsrf": "new-tok"}

    def test_xsrf_read_from_cookie_jar_including_httponly(self):
        """Connect marks RSC-XSRF HttpOnly — must come from page.context.cookies(),
        not document.cookie (which is blind to HttpOnly cookies)."""
        from vip.auth import _create_api_key_via_session

        page = self._page(
            [
                {"name": "other", "value": "v1"},
                {"name": "RSC-XSRF", "value": "tok-n", "httpOnly": True},
                {"name": "another", "value": "v2"},
            ]
        )

        me = self._httpx_response(json_data={"guid": "g"})
        keys_list = self._httpx_response(json_data=[])
        created = self._httpx_response(json_data={"id": "1", "key": "K" * 30})

        def get_side_effect(path, **_kw):
            return me if path.endswith("/v1/user") else keys_list

        patcher, client_cls, _client = self._patch_httpx_client(
            get_side_effect=get_side_effect,
            post_rv=created,
        )
        with patcher:
            _create_api_key_via_session(page, "https://c.example.com", "k")

        page.context.cookies.assert_called()
        assert client_cls.call_args.kwargs["headers"]["X-Rsc-Xsrf"] == "tok-n"

    def test_create_failure_returns_none(self, capsys):
        """HTTP 500 on the create call must yield None, not an exception.
        The warning must include a snippet of the response body."""
        from vip.auth import _create_api_key_via_session

        page = self._page()

        me = self._httpx_response(json_data={"guid": "g"})
        keys_list = self._httpx_response(json_data=[])
        failed = self._httpx_response(is_success=False, status_code=500, text="boom")

        def get_side_effect(path, **_kw):
            return me if path.endswith("/v1/user") else keys_list

        patcher, _cls, _client = self._patch_httpx_client(
            get_side_effect=get_side_effect,
            post_rv=failed,
        )
        with patcher:
            assert _create_api_key_via_session(page, "https://c.example.com", "k") is None

        assert "boom" in capsys.readouterr().out

    def test_user_endpoint_403_warning_includes_body(self, capsys):
        """When cookie auth is rejected at /v1/user, the response body must
        appear in the warning so users can diagnose the actual failure."""
        from vip.auth import _create_api_key_via_session

        page = self._page()
        me_403 = self._httpx_response(
            is_success=False,
            status_code=403,
            text='{"code": 23, "error": "CSRF token is required"}',
        )

        patcher, _cls, _client = self._patch_httpx_client(
            get_side_effect=lambda *_a, **_kw: me_403,
        )
        with patcher:
            assert _create_api_key_via_session(page, "https://c.example.com", "k") is None

        out = capsys.readouterr().out
        assert "HTTP 403" in out
        assert "CSRF token is required" in out

    def test_mint_failure_warning_includes_full_url_and_content_type(self, capsys):
        """The warning must print the full mint URL and Content-Type so the
        user can distinguish Connect's 404 page from an upstream proxy 404."""
        from vip.auth import _create_api_key_via_session

        page = self._page()
        me_404 = self._httpx_response(
            is_success=False,
            status_code=404,
            text="404 page not found\n",
            headers={"content-type": "text/plain; charset=utf-8"},
        )
        probe_404 = self._httpx_response(
            is_success=False,
            status_code=404,
            text="404 page not found\n",
            headers={"content-type": "text/plain; charset=utf-8"},
        )

        def get_side_effect(path, **_kw):
            return me_404 if path.endswith("/v1/user") else probe_404

        patcher, _cls, _client = self._patch_httpx_client(
            get_side_effect=get_side_effect,
        )
        with patcher:
            result = _create_api_key_via_session(page, "https://c.example.com/connect", "k")
        assert result is None

        out = capsys.readouterr().out
        # Full URL is reported, not just the relative path.
        assert "https://c.example.com/connect/__api__/v1/user" in out
        # Content-Type appears so users can spot Go-default vs Connect 404s.
        assert "text/plain" in out

    def test_mint_failure_404_probes_server_settings_and_hints_at_wrong_url(self, capsys):
        """When both /v1/user and /server_settings return 404, the diagnostic
        must suggest the connect_url path prefix is wrong — that's the only
        plausible cause (the server settings endpoint is unauthenticated)."""
        from vip.auth import _create_api_key_via_session

        page = self._page()
        not_found = self._httpx_response(
            is_success=False,
            status_code=404,
            text="404 page not found\n",
            headers={"content-type": "text/plain; charset=utf-8"},
        )

        calls: list[str] = []

        def get_side_effect(path, **_kw):
            calls.append(path)
            return not_found

        patcher, _cls, _client = self._patch_httpx_client(
            get_side_effect=get_side_effect,
        )
        with patcher:
            _create_api_key_via_session(page, "https://c.example.com/connect", "k")

        assert "/v1/user" in calls
        assert "/server_settings" in calls

        out = capsys.readouterr().out
        assert "/server_settings returned HTTP 404" in out
        assert "wrong path prefix" in out
        assert "https://c.example.com/connect" in out

    def test_mint_failure_403_does_not_hint_at_wrong_url(self, capsys):
        """A 403 on /v1/user is auth rejection, not a routing problem — the
        'wrong path prefix' hint must only fire when both endpoints 404."""
        from vip.auth import _create_api_key_via_session

        page = self._page()
        me_403 = self._httpx_response(
            is_success=False,
            status_code=403,
            text="forbidden",
            headers={"content-type": "application/json"},
        )
        probe_200 = self._httpx_response(
            json_data={"version": "2024.09.0"},
            headers={"content-type": "application/json"},
        )

        def get_side_effect(path, **_kw):
            return me_403 if path.endswith("/v1/user") else probe_200

        patcher, _cls, _client = self._patch_httpx_client(
            get_side_effect=get_side_effect,
        )
        with patcher:
            _create_api_key_via_session(page, "https://c.example.com", "k")

        out = capsys.readouterr().out
        assert "/server_settings returned HTTP 200" in out
        assert "wrong path prefix" not in out

    def test_mint_failure_probe_transport_error_logged_not_raised(self, capsys):
        """If the /server_settings probe itself raises, that must not mask the
        original /v1/user warning — log the probe failure and move on."""
        import httpx

        from vip.auth import _create_api_key_via_session

        page = self._page()
        me_404 = self._httpx_response(
            is_success=False,
            status_code=404,
            text="404 page not found",
            headers={"content-type": "text/plain"},
        )

        def get_side_effect(path, **_kw):
            if path.endswith("/v1/user"):
                return me_404
            raise httpx.ReadTimeout("probe timed out")

        patcher, _cls, _client = self._patch_httpx_client(
            get_side_effect=get_side_effect,
        )
        with patcher:
            result = _create_api_key_via_session(page, "https://c.example.com", "k")
        assert result is None

        out = capsys.readouterr().out
        assert "/server_settings probe failed" in out
        assert "probe timed out" in out

    def test_httpx_transport_error_returns_none(self, capsys):
        """httpx connection failures (DNS, TCP, TLS) must return None, not bubble up.

        The function is documented to return None on failure rather than raise,
        so vip verify can emit a warning and proceed to other checks.  Without
        an httpx.HTTPError catch, a TLS rejection (verify=True against a
        self-signed server) would crash auth setup instead.
        """
        import httpx

        from vip.auth import _create_api_key_via_session

        page = self._page()

        def raise_connect_error(*_a, **_kw):
            raise httpx.ConnectError("simulated TLS rejection")

        patcher, _cls, _client = self._patch_httpx_client(get_side_effect=raise_connect_error)
        with patcher:
            assert _create_api_key_via_session(page, "https://c.example.com", "k") is None

        assert "simulated TLS rejection" in capsys.readouterr().out

    def test_missing_xsrf_cookie_still_runs(self):
        """With no RSC-XSRF cookie the call still runs; no X-Rsc-Xsrf header sent."""
        from vip.auth import _create_api_key_via_session

        page = self._page([{"name": "connect-session", "value": "sess"}])  # no RSC-XSRF

        me = self._httpx_response(json_data={"guid": "g"})
        keys_list = self._httpx_response(json_data=[])
        created = self._httpx_response(json_data={"id": "1", "key": "K" * 30})

        def get_side_effect(path, **_kw):
            return me if path.endswith("/v1/user") else keys_list

        patcher, client_cls, _client = self._patch_httpx_client(
            get_side_effect=get_side_effect,
            post_rv=created,
        )
        with patcher:
            result = _create_api_key_via_session(page, "https://c.example.com", "k")

        assert result == "K" * 30
        # No X-Rsc-Xsrf header when the cookie is absent.
        assert "X-Rsc-Xsrf" not in client_cls.call_args.kwargs["headers"]

    def test_unexpected_key_list_shape_does_not_crash(self):
        """If Connect returns a non-list for the keys endpoint, creation must
        still succeed — cleanup is best-effort."""
        from vip.auth import _create_api_key_via_session

        page = self._page()

        me = self._httpx_response(json_data={"guid": "g"})
        bad_keys = self._httpx_response(json_data={"error": "nope"})  # dict, not list
        created = self._httpx_response(json_data={"id": "9", "key": "K" * 30})

        def get_side_effect(path, **_kw):
            return me if path.endswith("/v1/user") else bad_keys

        patcher, _cls, _client = self._patch_httpx_client(
            get_side_effect=get_side_effect,
            post_rv=created,
        )
        with patcher:
            assert _create_api_key_via_session(page, "https://c.example.com", "k") == "K" * 30

    def test_non_dict_entries_in_key_list_are_skipped(self):
        """List entries that aren't dicts (and dicts missing id) must be silently skipped."""
        import time

        from vip.auth import _create_api_key_via_session

        old_ts = int(time.time()) - 7200
        deletes: list[str] = []

        page = self._page()
        me = self._httpx_response(json_data={"guid": "g"})
        keys_list = self._httpx_response(
            json_data=[
                "not a dict",
                {"name": f"_vip_interactive_{old_ts}"},  # no id
                {"id": "5", "name": f"_vip_interactive_{old_ts}"},  # deletable
            ]
        )
        created = self._httpx_response(json_data={"id": "9", "key": "K" * 30})

        def get_side_effect(path, **_kw):
            return me if path.endswith("/v1/user") else keys_list

        def delete_side_effect(path, **_kw):
            deletes.append(path.rsplit("/", 1)[-1])
            return self._httpx_response(status_code=204)

        patcher, _cls, client_mock = self._patch_httpx_client(
            get_side_effect=get_side_effect,
            delete_side_effect=delete_side_effect,
            post_rv=created,
        )
        with patcher:
            assert _create_api_key_via_session(page, "https://c.example.com", "k") == "K" * 30

        assert deletes == ["5"]

    def test_missing_user_guid_returns_none(self):
        """If /v1/user returns no guid, function returns None and skips POST."""
        from vip.auth import _create_api_key_via_session

        page = self._page()
        me_no_guid = self._httpx_response(json_data={})

        patcher, _cls, client_mock = self._patch_httpx_client(
            get_side_effect=lambda *_a, **_kw: me_no_guid,
        )
        with patcher:
            assert _create_api_key_via_session(page, "https://c.example.com", "k") is None

        client_mock.post.assert_not_called()

    def test_xsrf_cookie_with_trailing_slash_path_is_included(self):
        """RFC 6265: cookies() must be called with an endpoint URL (not bare
        /__api__) so that path-scoped RSC-XSRF cookies are included."""
        from vip.auth import _create_api_key_via_session

        page = MagicMock()

        def cookies_for(url=None):
            if not url:
                return [{"name": "RSC-XSRF", "value": "tok", "path": "/__api__/"}]
            from urllib.parse import urlparse

            path = urlparse(url).path
            if path.startswith("/__api__/"):
                return [{"name": "RSC-XSRF", "value": "tok", "path": "/__api__/"}]
            return []

        page.context.cookies.side_effect = cookies_for

        me = self._httpx_response(json_data={"guid": "g"})
        keys_list = self._httpx_response(json_data=[])
        created = self._httpx_response(json_data={"id": "1", "key": "K" * 30})

        def get_side_effect(path, **_kw):
            return me if path.endswith("/v1/user") else keys_list

        patcher, client_cls, _client = self._patch_httpx_client(
            get_side_effect=get_side_effect,
            post_rv=created,
        )
        with patcher:
            result = _create_api_key_via_session(page, "https://connect.example.com", "k")

        assert result == "K" * 30, (
            "cookie with Path=/__api__/ must be read; request to /__api__ "
            "(no trailing slash) would miss it under RFC 6265 path matching."
        )
        assert client_cls.call_args.kwargs["headers"].get("X-Rsc-Xsrf") == "tok"

    def test_xsrf_cookie_is_scoped_to_api_url(self):
        """cookies() must be called with a URL under /__api__ so that
        cross-domain RSC-XSRF cookies from the IdP are excluded."""
        from vip.auth import _create_api_key_via_session

        page = MagicMock()
        api_base = "https://connect.example.com/__api__"

        def cookies_for(url=None):
            if url and url.startswith(api_base):
                return [{"name": "RSC-XSRF", "value": "real", "path": "/__api__"}]
            return [
                {"name": "RSC-XSRF", "value": "real", "path": "/__api__"},
                {"name": "RSC-XSRF", "value": "stranger", "domain": "idp.elsewhere.io"},
            ]

        page.context.cookies.side_effect = cookies_for

        me = self._httpx_response(json_data={"guid": "g"})
        keys_list = self._httpx_response(json_data=[])
        created = self._httpx_response(json_data={"id": "1", "key": "K" * 30})

        def get_side_effect(path, **_kw):
            return me if path.endswith("/v1/user") else keys_list

        patcher, client_cls, _client = self._patch_httpx_client(
            get_side_effect=get_side_effect,
            post_rv=created,
        )
        with patcher:
            result = _create_api_key_via_session(page, "https://connect.example.com", "k")

        assert result == "K" * 30
        assert client_cls.call_args.kwargs["headers"].get("X-Rsc-Xsrf") == "real"
        # Confirm cookies() was called with a URL under /__api__.
        scoped_calls = [
            call for call in page.context.cookies.call_args_list if call.args and call.args[0]
        ]
        assert scoped_calls, "page.context.cookies() was never called with a URL"
        for call in scoped_calls:
            assert call.args[0].startswith(api_base), (
                f"cookies() URL {call.args[0]!r} is not under {api_base!r}; "
                "path-scoped RSC-XSRF cookies would be missed."
            )


class TestHeadlessAuthTLSFlags:
    """start_headless_auth passes TLS config to browser.new_context()."""

    def _make_playwright_stub(self) -> MagicMock:
        """Stub sync_playwright() that raises PlaywrightTimeoutError on goto
        (so the test terminates quickly without completing auth)."""
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

        with patch("vip.auth.sync_playwright", return_value=stub):
            with pytest.raises(Exception):  # timeout or AuthConfigError
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

        with patch("vip.auth.sync_playwright", return_value=stub):
            with pytest.raises(Exception):
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

        with patch("vip.auth.sync_playwright", return_value=stub):
            with pytest.raises(Exception):
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

        with patch("vip.auth.sync_playwright", return_value=stub):
            with pytest.raises(Exception):
                start_headless_auth(
                    connect_url="https://c.example.com",
                    username="user",
                    password="pass",
                    ca_bundle=Path(ca_file),
                )

        assert os.environ.get("NODE_EXTRA_CA_CERTS") == prev_value
