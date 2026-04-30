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


class TestCreateApiKeyViaSession:
    """_create_api_key_via_session routes through Playwright's
    APIRequestContext (``page.context.request``) so cookies and XSRF
    tokens ride the live browser session, sidestepping the cookiejar
    re-encoding that broke earlier httpx-based attempts."""

    @staticmethod
    def _api_response(
        *,
        ok: bool = True,
        status: int = 200,
        json_data=None,
        text_data: str = "",
    ) -> MagicMock:
        """Stub a Playwright APIResponse with the given shape."""
        resp = MagicMock()
        resp.ok = ok
        resp.status = status
        resp.json.return_value = json_data if json_data is not None else {}
        resp.text.return_value = text_data
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

    def test_happy_path_creates_key_and_sends_xsrf(self):
        """List is empty (no orphans), POST returns a key string.
        Every request must go through ``page.context.request`` with the
        XSRF header taken from ``document.cookie``."""
        from vip.auth import _create_api_key_via_session

        page = self._page(
            [
                {"name": "RSC-XSRF", "value": "xsrf-token", "httpOnly": True},
                {"name": "connect-session", "value": "sess-123", "httpOnly": True},
            ]
        )
        req = page.context.request

        me = self._api_response(json_data={"guid": "user-guid-abc"})
        keys_list = self._api_response(json_data=[])
        created = self._api_response(
            json_data={"id": "7", "name": "_vip_interactive_1", "key": "SECRETKEY" * 3}
        )

        def get_side_effect(url, **_kwargs):
            return me if url.endswith("/v1/user") else keys_list

        req.get.side_effect = get_side_effect
        req.post.return_value = created

        result = _create_api_key_via_session(
            page, "https://connect.example.com", "_vip_interactive_1"
        )

        assert result == "SECRETKEY" * 3

        # GET /v1/user must carry the XSRF header derived from document.cookie.
        me_call = req.get.call_args_list[0]
        assert me_call.args[0] == "https://connect.example.com/__api__/v1/user"
        assert me_call.kwargs["headers"]["X-Rsc-Xsrf"] == "xsrf-token"

        # POST must carry the XSRF header and a JSON body with the key name.
        post_call = req.post.call_args
        assert post_call.args[0].endswith("/v1/users/user-guid-abc/keys")
        assert post_call.kwargs["headers"]["X-Rsc-Xsrf"] == "xsrf-token"
        assert post_call.kwargs["data"] == {"name": "_vip_interactive_1"}

    def test_deletes_orphan_vip_keys_before_creating(self):
        """Old _vip_interactive_<ts> keys must be deleted before the POST."""
        import time

        from vip.auth import _create_api_key_via_session

        old_ts = int(time.time()) - 7200
        call_order: list[tuple[str, str | None]] = []

        page = self._page()
        req = page.context.request

        me = self._api_response(json_data={"guid": "g"})
        keys_list = self._api_response(
            json_data=[
                {"id": "1", "name": f"_vip_interactive_{old_ts}"},
                {"id": "2", "name": "my-personal-key"},
                {"id": "3", "name": f"_vip_interactive_{old_ts - 100}"},
            ]
        )

        def get_side_effect(url, **_kwargs):
            return me if url.endswith("/v1/user") else keys_list

        def delete_side_effect(url, **_kwargs):
            call_order.append(("DELETE", url.rsplit("/", 1)[-1]))
            return self._api_response(status=204)

        def post_side_effect(url, **_kwargs):
            call_order.append(("POST", None))
            return self._api_response(json_data={"id": "9", "key": "NEWKEY" * 5})

        req.get.side_effect = get_side_effect
        req.delete.side_effect = delete_side_effect
        req.post.side_effect = post_side_effect

        result = _create_api_key_via_session(page, "https://c.example.com", "_vip_interactive_new")

        assert result == "NEWKEY" * 5

        deleted_ids = [kid for (op, kid) in call_order if op == "DELETE"]
        assert sorted(deleted_ids) == ["1", "3"]

        # All DELETEs must come strictly before the POST — otherwise a flaky
        # Connect version could see the new key during listing and delete it.
        post_index = next(i for i, (op, _) in enumerate(call_order) if op == "POST")
        assert all(op == "DELETE" for op, _ in call_order[:post_index])
        assert post_index == len(call_order) - 1  # POST is last, ran once

    def test_skips_recent_orphan_keys(self):
        """Keys younger than _ORPHAN_MIN_AGE_SECONDS must NOT be deleted —
        they likely belong to a concurrent vip verify run."""
        import time

        from vip.auth import _create_api_key_via_session

        recent_ts = int(time.time()) - 60  # 60s old: belongs to a live run

        page = self._page()
        req = page.context.request

        me = self._api_response(json_data={"guid": "g"})
        keys_list = self._api_response(
            json_data=[{"id": "42", "name": f"_vip_interactive_{recent_ts}"}]
        )
        created = self._api_response(json_data={"id": "9", "key": "K" * 30})

        def get_side_effect(url, **_kwargs):
            return me if url.endswith("/v1/user") else keys_list

        req.get.side_effect = get_side_effect
        req.post.return_value = created

        result = _create_api_key_via_session(page, "https://c.example.com", "_vip_interactive_new")

        assert result == "K" * 30
        req.delete.assert_not_called()  # recent key was left alone

    def test_xsrf_falls_back_to_legacy_cookie_name(self):
        """Servers in legacy cookie mode (e.g. ``connect.posit.it``) set
        ``RSC-XSRF-legacy`` instead of ``RSC-XSRF``.  The paired session
        cookie is ``rsconnect-legacy``; the header name stays the same.
        Without this fallback, Connect rejects every request with
        ``HTTP 403 XSRF token mismatch``."""
        from vip.auth import _create_api_key_via_session

        page = self._page(
            [
                {"name": "RSC-XSRF-legacy", "value": "legacy-tok"},
                {"name": "rsconnect-legacy", "value": "sess", "httpOnly": True},
            ]
        )
        req = page.context.request

        req.get.side_effect = [
            self._api_response(json_data={"guid": "g"}),
            self._api_response(json_data=[]),
        ]
        req.post.return_value = self._api_response(json_data={"id": "1", "key": "K" * 30})

        result = _create_api_key_via_session(page, "https://c.example.com", "k")

        assert result == "K" * 30
        assert req.get.call_args_list[0].kwargs["headers"]["X-Rsc-Xsrf"] == "legacy-tok"

    def test_xsrf_prefers_modern_name_when_both_present(self):
        """If both ``RSC-XSRF`` and ``RSC-XSRF-legacy`` are set, use the
        modern one — servers mid-migration tend to honor the new name."""
        from vip.auth import _create_api_key_via_session

        page = self._page(
            [
                {"name": "RSC-XSRF", "value": "new-tok"},
                {"name": "RSC-XSRF-legacy", "value": "old-tok"},
            ]
        )
        req = page.context.request

        req.get.side_effect = [
            self._api_response(json_data={"guid": "g"}),
            self._api_response(json_data=[]),
        ]
        req.post.return_value = self._api_response(json_data={"id": "1", "key": "K" * 30})

        _create_api_key_via_session(page, "https://c.example.com", "k")

        assert req.get.call_args_list[0].kwargs["headers"]["X-Rsc-Xsrf"] == "new-tok"

    def test_xsrf_read_from_cookie_jar_including_httponly(self):
        """Connect marks ``RSC-XSRF`` ``HttpOnly`` — the real reason earlier
        attempts saw ``HTTP 403 XSRF token mismatch``.  ``document.cookie``
        is blind to HttpOnly cookies, so the XSRF value must come from
        ``page.context.cookies()`` (the browser's cookie jar), which
        Playwright exposes regardless of the flag."""
        from vip.auth import _create_api_key_via_session

        page = self._page(
            [
                {"name": "other", "value": "v1"},
                {"name": "RSC-XSRF", "value": "tok-n", "httpOnly": True},
                {"name": "another", "value": "v2"},
            ]
        )
        req = page.context.request

        req.get.side_effect = [
            self._api_response(json_data={"guid": "g"}),
            self._api_response(json_data=[]),
        ]
        req.post.return_value = self._api_response(json_data={"id": "1", "key": "K" * 30})

        _create_api_key_via_session(page, "https://c.example.com", "k")

        page.context.cookies.assert_called()
        post_call = req.post.call_args
        # Exact byte-for-byte match: no URL-decoding, no quoting, no stripping.
        assert post_call.kwargs["headers"]["X-Rsc-Xsrf"] == "tok-n"

    def test_create_failure_returns_none(self, capsys):
        """HTTP 500 on the create call must yield None, not an exception.
        The warning must include a snippet of the response body so the user
        can diagnose what Connect rejected."""
        from vip.auth import _create_api_key_via_session

        page = self._page()
        req = page.context.request

        req.get.side_effect = [
            self._api_response(json_data={"guid": "g"}),
            self._api_response(json_data=[]),
        ]
        req.post.return_value = self._api_response(ok=False, status=500, text_data="boom")

        assert _create_api_key_via_session(page, "https://c.example.com", "k") is None
        assert "boom" in capsys.readouterr().out

    def test_user_endpoint_403_warning_includes_body(self, capsys):
        """When cookie auth is rejected at /v1/user, the response body often
        tells us why (CSRF, Origin, MFA step-up).  Include it in the warning
        so users can report the real failure instead of an opaque 403."""
        from vip.auth import _create_api_key_via_session

        page = self._page()
        req = page.context.request

        req.get.return_value = self._api_response(
            ok=False,
            status=403,
            text_data='{"code": 23, "error": "CSRF token is required"}',
        )

        assert _create_api_key_via_session(page, "https://c.example.com", "k") is None
        out = capsys.readouterr().out
        assert "HTTP 403" in out
        assert "CSRF token is required" in out

    def test_missing_xsrf_cookie_still_runs(self):
        """With no RSC-XSRF cookie the call still runs; no X-Rsc-Xsrf header sent."""
        from vip.auth import _create_api_key_via_session

        page = self._page([{"name": "connect-session", "value": "sess"}])  # no RSC-XSRF
        req = page.context.request

        req.get.side_effect = [
            self._api_response(json_data={"guid": "g"}),
            self._api_response(json_data=[]),
        ]
        req.post.return_value = self._api_response(json_data={"id": "1", "key": "K" * 30})

        result = _create_api_key_via_session(page, "https://c.example.com", "k")

        assert result == "K" * 30
        # No header — and definitely not the literal empty string either.
        assert "X-Rsc-Xsrf" not in req.post.call_args.kwargs["headers"]
        assert "X-Rsc-Xsrf" not in req.get.call_args_list[0].kwargs["headers"]

    def test_unexpected_key_list_shape_does_not_crash(self):
        """If Connect returns a non-list (or a list with non-dict items) for
        the keys endpoint, creation must still succeed — cleanup is
        best-effort and shape surprises must not raise."""
        from vip.auth import _create_api_key_via_session

        page = self._page()
        req = page.context.request

        req.get.side_effect = [
            self._api_response(json_data={"guid": "g"}),
            self._api_response(json_data={"error": "nope"}),  # dict, not list
        ]
        req.post.return_value = self._api_response(json_data={"id": "9", "key": "K" * 30})

        assert _create_api_key_via_session(page, "https://c.example.com", "k") == "K" * 30

    def test_non_dict_entries_in_key_list_are_skipped(self):
        """List entries that aren't dicts (and dicts missing id) must be
        silently skipped rather than crashing cleanup."""
        import time

        from vip.auth import _create_api_key_via_session

        old_ts = int(time.time()) - 7200
        deletes: list[str] = []

        page = self._page()
        req = page.context.request

        req.get.side_effect = [
            self._api_response(json_data={"guid": "g"}),
            self._api_response(
                json_data=[
                    "not a dict",
                    {"name": f"_vip_interactive_{old_ts}"},  # no id
                    {"id": "5", "name": f"_vip_interactive_{old_ts}"},  # deletable
                ]
            ),
        ]

        def delete_side_effect(url, **_kwargs):
            deletes.append(url.rsplit("/", 1)[-1])
            return self._api_response(status=204)

        req.delete.side_effect = delete_side_effect
        req.post.return_value = self._api_response(json_data={"id": "9", "key": "K" * 30})

        assert _create_api_key_via_session(page, "https://c.example.com", "k") == "K" * 30
        assert deletes == ["5"]  # only the well-formed entry was deleted

    def test_missing_user_guid_returns_none(self):
        """If /v1/user returns no guid, function returns None and skips POST."""
        from vip.auth import _create_api_key_via_session

        page = self._page()
        req = page.context.request

        req.get.return_value = self._api_response(json_data={})  # no guid

        assert _create_api_key_via_session(page, "https://c.example.com", "k") is None
        req.post.assert_not_called()

    def test_xsrf_cookie_with_trailing_slash_path_is_included(self):
        """RFC 6265 path matching: a cookie with ``Path=/__api__/`` is sent
        only with requests whose path is under ``/__api__/`` — ``/__api__``
        alone (no trailing slash) does *not* match.  Scoping ``cookies()``
        to the base (``/__api__``) excludes these cookies even though they
        *will* ride every real API call.  Use an actual endpoint URL so
        Playwright's filter sees a matching request-path.
        """
        from vip.auth import _create_api_key_via_session

        page = MagicMock()

        def cookies_for(url=None):
            # Stub RFC 6265-compliant filtering: return the cookie only if
            # the URL's path is under ``/__api__/``.
            if not url:
                return [{"name": "RSC-XSRF", "value": "tok", "path": "/__api__/"}]
            from urllib.parse import urlparse

            path = urlparse(url).path
            if path.startswith("/__api__/"):
                return [{"name": "RSC-XSRF", "value": "tok", "path": "/__api__/"}]
            return []

        page.context.cookies.side_effect = cookies_for
        req = page.context.request

        req.get.side_effect = [
            self._api_response(json_data={"guid": "g"}),
            self._api_response(json_data=[]),
        ]
        req.post.return_value = self._api_response(json_data={"id": "1", "key": "K" * 30})

        result = _create_api_key_via_session(page, "https://connect.example.com", "k")

        assert result == "K" * 30, (
            "cookie with Path=/__api__/ must be read; request to /__api__ "
            "(no trailing slash) would miss it under RFC 6265 path matching."
        )
        assert req.get.call_args_list[0].kwargs["headers"]["X-Rsc-Xsrf"] == "tok"

    def test_xsrf_cookie_is_scoped_to_api_url(self):
        """Cookie jars from ``page.context.cookies()`` span every domain the
        browser has touched — IdP, related subdomains, etc.  Unfiltered
        reads let a ``RSC-XSRF`` from another site shadow Connect's and
        yield ``HTTP 403 XSRF token mismatch``.  Playwright's ``cookies(url)``
        filter is host *and path* aware, so the URL we pass must match
        the path the request will actually hit (``/__api__/...``), not
        just the root — otherwise a cookie set with ``Path=/__api__``
        will be silently excluded.
        """
        from vip.auth import _create_api_key_via_session

        page = MagicMock()
        api_base = "https://connect.example.com/__api__"

        def cookies_for(url=None):
            # Playwright filters server-side; our stub mirrors that: the
            # real cookie lives at ``/__api__/`` and must be included, the
            # unrelated domain's cookie must not.
            if url and url.startswith(api_base):
                return [{"name": "RSC-XSRF", "value": "real", "path": "/__api__"}]
            return [
                {"name": "RSC-XSRF", "value": "real", "path": "/__api__"},
                {"name": "RSC-XSRF", "value": "stranger", "domain": "idp.elsewhere.io"},
            ]

        page.context.cookies.side_effect = cookies_for
        req = page.context.request

        req.get.side_effect = [
            self._api_response(json_data={"guid": "g"}),
            self._api_response(json_data=[]),
        ]
        req.post.return_value = self._api_response(json_data={"id": "1", "key": "K" * 30})

        result = _create_api_key_via_session(page, "https://connect.example.com", "k")

        assert result == "K" * 30
        assert req.get.call_args_list[0].kwargs["headers"]["X-Rsc-Xsrf"] == "real"
        # URL passed to cookies() must be under /__api__ so path-scoped
        # cookies aren't excluded by Playwright's path filter.
        scoped_calls = [
            call for call in page.context.cookies.call_args_list if call.args and call.args[0]
        ]
        assert scoped_calls, "page.context.cookies() was never called with a URL"
        for call in scoped_calls:
            assert call.args[0].startswith(api_base), (
                f"cookies() URL {call.args[0]!r} is not under {api_base!r}; "
                "path-scoped RSC-XSRF cookies would be missed."
            )

    def test_uses_page_context_request_so_xsrf_matches_cookie(self):
        """Regression guard: requests must go through ``page.context.request``
        (Playwright's APIRequestContext), which shares the browser's cookie
        jar.  Sending cookies through httpx re-encodes them, breaking
        Connect's double-submit XSRF check: the RSC-XSRF cookie value seen
        by the server then no longer equals the X-Rsc-Xsrf header value.
        """
        from vip.auth import _create_api_key_via_session

        page = self._page(
            [
                {"name": "RSC-XSRF", "value": "live-token", "httpOnly": True},
                {"name": "connect-session", "value": "s", "httpOnly": True},
            ]
        )
        req = page.context.request

        req.get.side_effect = [
            self._api_response(json_data={"guid": "g"}),
            self._api_response(json_data=[]),
        ]
        req.post.return_value = self._api_response(json_data={"id": "1", "key": "K" * 30})

        result = _create_api_key_via_session(page, "https://c.example.com", "k")

        assert result == "K" * 30
        assert req.get.called, "GET /v1/user must route through page.context.request"
        assert req.post.call_args.kwargs["headers"]["X-Rsc-Xsrf"] == "live-token"


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
        """Without insecure, new_context should not receive ignore_https_errors=True."""
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
        assert not kwargs.get("ignore_https_errors")
