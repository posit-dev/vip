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


class TestCreateApiKeyViaSession:
    """_create_api_key_via_session talks to Connect's REST API using
    cookies lifted from the authenticated Playwright context."""

    def _page_with_cookies(self, cookies: list[dict]) -> MagicMock:
        """Return a stub Playwright Page whose context.cookies() is set."""
        page = MagicMock()
        page.context.cookies.return_value = cookies
        return page

    def _transport(self, handler):
        """Wrap a request -> Response handler in a MockTransport."""
        import httpx

        return httpx.MockTransport(handler)

    def test_happy_path_creates_key_and_sends_xsrf(self, monkeypatch):
        """List is empty (no orphans), POST returns a key string."""
        import httpx

        from vip.auth import _create_api_key_via_session

        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.setdefault("requests", []).append(request)
            if request.method == "GET" and request.url.path == "/__api__/v1/user":
                return httpx.Response(200, json={"guid": "user-guid-abc"})
            if (
                request.method == "GET"
                and request.url.path == "/__api__/v1/users/user-guid-abc/keys"
            ):
                return httpx.Response(200, json=[])
            if (
                request.method == "POST"
                and request.url.path == "/__api__/v1/users/user-guid-abc/keys"
            ):
                return httpx.Response(
                    200,
                    json={
                        "id": "7",
                        "name": "_vip_interactive_1",
                        "key": "SECRETKEY" * 3,
                    },
                )
            return httpx.Response(404)

        # auth.py imports httpx inside the function, so patching the real
        # module's Client is what the call site will resolve via sys.modules.
        real_client = httpx.Client

        def fake_client(*args, **kwargs):
            kwargs["transport"] = self._transport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", fake_client)

        page = self._page_with_cookies(
            [
                {"name": "connect-session", "value": "sess-123"},
                {"name": "RSC-XSRF", "value": "xsrf-token"},
            ]
        )

        result = _create_api_key_via_session(
            page, "https://connect.example.com", "_vip_interactive_1"
        )

        assert result == "SECRETKEY" * 3

        # Every outbound request must carry the session cookie so Connect's
        # cookie-based auth accepts it.
        for req in captured["requests"]:
            assert "connect-session=sess-123" in req.headers.get("cookie", "")

        # The POST request must include the XSRF header and the expected body.
        post_reqs = [r for r in captured["requests"] if r.method == "POST"]
        assert len(post_reqs) == 1
        assert post_reqs[0].headers.get("X-Rsc-Xsrf") == "xsrf-token"
        import json as _json

        assert _json.loads(post_reqs[0].content) == {"name": "_vip_interactive_1"}

    def test_deletes_orphan_vip_keys_before_creating(self, monkeypatch):
        """Keys whose name starts with _vip_interactive_ must be deleted first."""
        import httpx

        from vip.auth import _create_api_key_via_session

        deletes: list[str] = []
        posts: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path == "/__api__/v1/user":
                return httpx.Response(200, json={"guid": "g"})
            if request.method == "GET" and request.url.path == "/__api__/v1/users/g/keys":
                return httpx.Response(
                    200,
                    json=[
                        {"id": "1", "name": "_vip_interactive_old1"},
                        {"id": "2", "name": "my-personal-key"},
                        {"id": "3", "name": "_vip_interactive_old2"},
                    ],
                )
            if request.method == "DELETE" and request.url.path.startswith(
                "/__api__/v1/users/g/keys/"
            ):
                deletes.append(request.url.path.rsplit("/", 1)[-1])
                return httpx.Response(204)
            if request.method == "POST" and request.url.path == "/__api__/v1/users/g/keys":
                posts.append(request)
                return httpx.Response(200, json={"id": "9", "key": "NEWKEY" * 5})
            return httpx.Response(404)

        real_client = httpx.Client

        def fake_client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", fake_client)

        page = self._page_with_cookies([{"name": "RSC-XSRF", "value": "x"}])
        result = _create_api_key_via_session(page, "https://c.example.com", "_vip_interactive_new")

        assert result == "NEWKEY" * 5
        assert sorted(deletes) == ["1", "3"]
        assert len(posts) == 1  # create ran after cleanup

    def test_create_failure_returns_none(self, monkeypatch):
        """HTTP 500 on the create call must yield None, not an exception."""
        import httpx

        from vip.auth import _create_api_key_via_session

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path == "/__api__/v1/user":
                return httpx.Response(200, json={"guid": "g"})
            if request.method == "GET" and request.url.path == "/__api__/v1/users/g/keys":
                return httpx.Response(200, json=[])
            if request.method == "POST" and request.url.path == "/__api__/v1/users/g/keys":
                return httpx.Response(500, text="boom")
            return httpx.Response(404)

        real_client = httpx.Client

        def fake_client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", fake_client)

        page = self._page_with_cookies([{"name": "RSC-XSRF", "value": "x"}])
        assert _create_api_key_via_session(page, "https://c.example.com", "k") is None

    def test_missing_xsrf_cookie_still_runs(self, monkeypatch):
        """With no RSC-XSRF cookie the call still runs; no X-Rsc-Xsrf header sent."""
        import httpx

        from vip.auth import _create_api_key_via_session

        seen_headers: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_headers.append(dict(request.headers))
            if request.method == "GET" and request.url.path == "/__api__/v1/user":
                return httpx.Response(200, json={"guid": "g"})
            if request.method == "GET" and request.url.path == "/__api__/v1/users/g/keys":
                return httpx.Response(200, json=[])
            if request.method == "POST" and request.url.path == "/__api__/v1/users/g/keys":
                return httpx.Response(200, json={"id": "1", "key": "K" * 30})
            return httpx.Response(404)

        real_client = httpx.Client

        def fake_client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", fake_client)

        page = self._page_with_cookies(
            [{"name": "connect-session", "value": "sess"}]  # no RSC-XSRF
        )
        result = _create_api_key_via_session(page, "https://c.example.com", "k")

        assert result == "K" * 30
        for h in seen_headers:
            assert "x-rsc-xsrf" not in {k.lower() for k in h}

    def test_missing_user_guid_returns_none(self, monkeypatch):
        """If /v1/user returns no guid, function returns None and skips POST."""
        import httpx

        from vip.auth import _create_api_key_via_session

        post_calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal post_calls
            if request.method == "GET" and request.url.path == "/__api__/v1/user":
                return httpx.Response(200, json={})  # no guid
            if request.method == "POST":
                post_calls += 1
            return httpx.Response(404)

        real_client = httpx.Client

        def fake_client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", fake_client)

        page = self._page_with_cookies([{"name": "RSC-XSRF", "value": "x"}])
        assert _create_api_key_via_session(page, "https://c.example.com", "k") is None
        assert post_calls == 0
