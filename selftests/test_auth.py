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
    crash the pytest session — Connect tests should still run."""

    def test_playwright_error_on_goto_is_non_fatal(self, capsys):
        """A PlaywrightError from page.goto() (e.g. ERR_CONNECTION_REFUSED,
        redirect-to-http) must be caught, logged as a warning, and return
        cleanly.  Otherwise the whole pytest session dies with INTERNALERROR.
        See issue #171."""
        from playwright.sync_api import Error as PlaywrightError

        from vip.auth import _authenticate_workbench

        page = MagicMock()
        page.goto.side_effect = PlaywrightError(
            "net::ERR_CONNECTION_REFUSED at https://wb.example.com/pwb"
        )

        _authenticate_workbench(page, "https://wb.example.com/pwb")

        out = capsys.readouterr().out
        assert "Could not reach Workbench" in out
        assert "https://wb.example.com/pwb" in out


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
    ) -> MagicMock:
        """Stub an httpx Response with the given shape."""
        resp = MagicMock()
        resp.is_success = is_success
        resp.status_code = status_code
        resp.json.return_value = json_data if json_data is not None else {}
        resp.text = text
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

        # POST must include the key name.
        post_call = client_mock.post.call_args
        assert post_call.args[0].endswith("/v1/users/user-guid-abc/keys")
        assert post_call.kwargs["data"] == {"name": "_vip_interactive_1"}

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
