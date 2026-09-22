"""Tests for vip.auth module — Connect API key minting."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


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
        skip the probe entirely.
        """
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
        product — refuse to switch.
        """
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
        endpoint that just happens to answer JSON 200.
        """
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
        ambiguous and keep the original URL.
        """
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
        Refuse to switch.
        """
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
        guide the user.
        """
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
        cookies extracted from the browser session.
        """
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

    def test_follows_redirects(self):
        """follow_redirects=True must be set so an http->https (or trailing-
        slash) redirect isn't treated as a mint failure (issue #537).
        Matches _resolve_connect_api_base's probes, which already do this.
        """
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
            _create_api_key_via_session(page, "https://c.example.com", "k")

        assert client_cls.call_args.kwargs["follow_redirects"] is True

    def test_returns_none_when_post_response_is_a_list(self):
        """A 301/302 on the key-creation POST must degrade to None, not crash.

        httpx (like browsers and curl) downgrades POST to GET when following a
        301 or 302 -- only 307/308 preserve the method.  The downgraded GET
        lands on the same path, which is Connect's key-*listing* route, so the
        response body is a JSON array rather than the created-key object.
        Calling ``.get("key")`` on that list raises ``AttributeError``, which
        is not in the caught tuple, so it escaped and took the whole run down
        (issue #561).  ``follow_redirects=True`` (issue #537) is what put this
        path in reach: before it, the redirect came back as not-success and
        the function returned None on its own.

        The function is documented to return the key or None on failure, so a
        redirect it cannot interpret must take the None path.
        """
        from vip.auth import _create_api_key_via_session

        page = self._page()
        me = self._httpx_response(json_data={"guid": "g"})
        keys_list = self._httpx_response(json_data=[])
        # What the downgraded GET actually returns: the key-listing array.
        redirected_to_listing = self._httpx_response(
            json_data=[{"id": "1", "name": "_vip_interactive_1"}]
        )

        def get_side_effect(path, **_kw):
            return me if path.endswith("/v1/user") else keys_list

        patcher, _cls, _client = self._patch_httpx_client(
            get_side_effect=get_side_effect,
            post_rv=redirected_to_listing,
        )
        with patcher:
            result = _create_api_key_via_session(page, "https://c.example.com", "k")

        assert result is None

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
        so Connect does not reject with ``HTTP 403 XSRF token mismatch``.
        """
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
        not document.cookie (which is blind to HttpOnly cookies).
        """
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
        The warning must include a snippet of the response body.
        """
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
        appear in the warning so users can diagnose the actual failure.
        """
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
        user can distinguish Connect's 404 page from an upstream proxy 404.
        """
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
        plausible cause (the server settings endpoint is unauthenticated).
        """
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
        'wrong path prefix' hint must only fire when both endpoints 404.
        """
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
        original /v1/user warning — log the probe failure and move on.
        """
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
        """Httpx connection failures (DNS, TCP, TLS) must return None, not bubble up.

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
        still succeed — cleanup is best-effort.
        """
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

        patcher, _cls, _client_mock = self._patch_httpx_client(
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
        /__api__) so that path-scoped RSC-XSRF cookies are included.
        """
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
        cross-domain RSC-XSRF cookies from the IdP are excluded.
        """
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
