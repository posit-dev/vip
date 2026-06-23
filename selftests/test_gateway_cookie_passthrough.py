"""Tests for OIDC gateway cookie passthrough to httpx clients.

An OIDC forward-auth gateway (e.g. Okta proxy) sitting in front of Connect/Workbench
intercepts ``/__api__/...`` requests and 307-redirects to the IdP UNLESS a gateway
session cookie is present (e.g. ``ptd_auth`` scoped to ``.current.posit.team``).

VIP captures gateway cookies in the Playwright storage state but (before this fix)
never fed them to the httpx API clients.  This test suite confirms the bridge.

Tests in this file follow TDD: they were written first to document the desired
behavior, then the implementation was added to make them pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from vip.auth import InteractiveAuthSession
from vip.clients.connect import ConnectClient
from vip.clients.workbench import WorkbenchClient

# ---------------------------------------------------------------------------
# Playwright storage-state fixture helpers
# ---------------------------------------------------------------------------


def _write_storage_state(path: Path, cookies: list[dict]) -> None:
    """Write a minimal Playwright storage-state JSON to *path*."""
    path.write_text(json.dumps({"cookies": cookies, "origins": []}))


# ---------------------------------------------------------------------------
# InteractiveAuthSession.load_cookies
# ---------------------------------------------------------------------------


class TestLoadCookies:
    """InteractiveAuthSession.load_cookies() parses the Playwright storage-state
    JSON and returns an httpx.Cookies jar ready for injection into API clients.

    Critical properties:
    - Preserves domain so parent-domain cookies (e.g. ``.current.posit.team``)
      route correctly to subdomains like ``pub.current.posit.team``.
    - Preserves path so path-scoped cookies don't bleed across paths.
    - Returns an empty jar for a missing or unparseable file (graceful degradation).
    - Loads ALL cookies in the file, not just those for a specific hostname.
    """

    def test_returns_httpx_cookies_instance(self, tmp_path):
        state = tmp_path / "state.json"
        _write_storage_state(
            state,
            [{"name": "ptd_auth", "value": "tok123", "domain": ".example.com", "path": "/"}],
        )
        session = InteractiveAuthSession(storage_state_path=state)

        result = session.load_cookies()

        assert isinstance(result, httpx.Cookies)

    def test_loads_single_cookie_with_domain_and_path(self, tmp_path):
        state = tmp_path / "state.json"
        _write_storage_state(
            state,
            [{"name": "ptd_auth", "value": "tok123", "domain": ".posit.team", "path": "/"}],
        )
        session = InteractiveAuthSession(storage_state_path=state)

        cookies = session.load_cookies()

        # httpx.Cookies.get() ignores domain/path in lookup by default;
        # we verify presence via iteration or direct dict-like access.
        assert cookies.get("ptd_auth") == "tok123"

    def test_loads_multiple_cookies(self, tmp_path):
        state = tmp_path / "state.json"
        _write_storage_state(
            state,
            [
                {
                    "name": "ptd_auth",
                    "value": "gw-tok",
                    "domain": ".current.posit.team",
                    "path": "/",
                },
                {
                    "name": "rsconnect",
                    "value": "sess-abc",
                    "domain": "connect.current.posit.team",
                    "path": "/",
                },
                {
                    "name": "RSC-XSRF",
                    "value": "xsrf-val",
                    "domain": "connect.current.posit.team",
                    "path": "/__api__/",
                },
            ],
        )
        session = InteractiveAuthSession(storage_state_path=state)

        cookies = session.load_cookies()

        assert cookies.get("ptd_auth") == "gw-tok"
        assert cookies.get("rsconnect") == "sess-abc"
        assert cookies.get("RSC-XSRF") == "xsrf-val"

    def test_parent_domain_cookie_preserves_domain(self, tmp_path):
        """A gateway cookie scoped to ``.current.posit.team`` must have its
        domain preserved so httpx routes it to subdomains like
        ``pub.current.posit.team``."""
        state = tmp_path / "state.json"
        _write_storage_state(
            state,
            [{"name": "ptd_auth", "value": "gw", "domain": ".current.posit.team", "path": "/"}],
        )
        session = InteractiveAuthSession(storage_state_path=state)

        cookies = session.load_cookies()

        # Verify the cookie exists and the domain is preserved in the underlying
        # http.cookiejar entries (accessible via cookies.jar).
        found = False
        for cookie in cookies.jar:
            if cookie.name == "ptd_auth":
                found = True
                assert ".current.posit.team" in cookie.domain, (
                    f"Expected domain to contain '.current.posit.team', got {cookie.domain!r}"
                )
        assert found, "ptd_auth cookie was not found in the jar"

    def test_returns_empty_cookies_when_file_missing(self, tmp_path):
        state = tmp_path / "nonexistent.json"
        session = InteractiveAuthSession(storage_state_path=state)

        cookies = session.load_cookies()

        assert isinstance(cookies, httpx.Cookies)
        assert list(cookies.items()) == []

    def test_returns_empty_cookies_when_file_invalid_json(self, tmp_path):
        state = tmp_path / "state.json"
        state.write_text("{not valid json")
        session = InteractiveAuthSession(storage_state_path=state)

        cookies = session.load_cookies()

        assert isinstance(cookies, httpx.Cookies)
        assert list(cookies.items()) == []

    def test_returns_empty_cookies_when_cookies_key_missing(self, tmp_path):
        state = tmp_path / "state.json"
        state.write_text('{"origins": []}')  # no "cookies" key
        session = InteractiveAuthSession(storage_state_path=state)

        cookies = session.load_cookies()

        assert isinstance(cookies, httpx.Cookies)

    def test_skips_cookies_without_name(self, tmp_path):
        """Entries with a blank or missing name are silently ignored."""
        state = tmp_path / "state.json"
        _write_storage_state(
            state,
            [
                {"name": "", "value": "v1", "domain": ".example.com", "path": "/"},
                {"value": "v2", "domain": ".example.com", "path": "/"},
                {"name": "valid_cookie", "value": "v3", "domain": ".example.com", "path": "/"},
            ],
        )
        session = InteractiveAuthSession(storage_state_path=state)

        cookies = session.load_cookies()

        assert cookies.get("valid_cookie") == "v3"


# ---------------------------------------------------------------------------
# BaseClient / ConnectClient cookies parameter
# ---------------------------------------------------------------------------


class TestBaseClientCookiesParameter:
    """BaseClient.__init__ accepts an optional ``cookies`` parameter and
    injects it into the underlying httpx.Client so all requests carry those
    cookies.  Default (None) means no behavior change."""

    def test_connect_client_without_cookies_has_empty_jar(self):
        client = ConnectClient(base_url="https://connect.example.com", api_key="key")
        # httpx.Client.cookies is a Cookies object; it may be empty or non-empty
        # depending on default state — we only care it doesn't raise.
        assert client._client.cookies is not None

    def test_connect_client_with_cookies_injects_into_httpx(self):
        """Cookies passed to ConnectClient must be present in the httpx client."""
        jar = httpx.Cookies()
        jar.set("ptd_auth", "gw-tok", domain=".posit.team", path="/")

        client = ConnectClient(
            base_url="https://connect.example.com",
            api_key="key",
            cookies=jar,
        )

        assert client._client.cookies.get("ptd_auth") == "gw-tok"

    def test_workbench_client_with_cookies_injects_into_httpx(self):
        """Same treatment for WorkbenchClient."""
        jar = httpx.Cookies()
        jar.set("ptd_auth", "gw-tok", domain=".posit.team", path="/")

        client = WorkbenchClient(
            base_url="https://workbench.example.com",
            api_key="key",
            cookies=jar,
        )

        assert client._client.cookies.get("ptd_auth") == "gw-tok"

    def test_cookies_none_does_not_change_behavior(self):
        """Passing cookies=None is identical to not passing it at all."""
        c1 = ConnectClient(base_url="https://connect.example.com", api_key="key")
        c2 = ConnectClient(base_url="https://connect.example.com", api_key="key", cookies=None)

        # Both should have empty (or equivalent) cookie jars.
        assert list(c1._client.cookies.items()) == list(c2._client.cookies.items())

    def test_stored_cookies_accessible_via_property(self):
        """BaseClient must expose the injected cookies so subclasses can use them
        in ad-hoc httpx requests (e.g. fetch_content)."""
        jar = httpx.Cookies()
        jar.set("ptd_auth", "gw-tok", domain=".posit.team", path="/")

        client = ConnectClient(
            base_url="https://connect.example.com",
            api_key="key",
            cookies=jar,
        )

        assert client.cookies is not None
        assert client.cookies.get("ptd_auth") == "gw-tok"

    def test_cookies_none_gives_none_or_empty_via_property(self):
        """When no cookies passed, the property returns None or empty Cookies."""
        client = ConnectClient(base_url="https://connect.example.com", api_key="key")
        # Should not raise; value is either None or an empty Cookies object.
        prop = client.cookies
        if prop is not None:
            assert list(prop.items()) == []


# ---------------------------------------------------------------------------
# fetch_content carries gateway cookies
# ---------------------------------------------------------------------------


class TestFetchContentWithGatewayCookies:
    """ConnectClient.fetch_content must include the gateway cookies so an OIDC
    proxy does not redirect the content request to the IdP."""

    @staticmethod
    def _make_response(
        status_code: int,
        *,
        url: str,
        location: str | None = None,
        body: bytes = b"",
    ) -> httpx.Response:
        headers: dict[str, str] = {}
        if location is not None:
            headers["location"] = location
        return httpx.Response(
            status_code=status_code,
            headers=headers,
            content=body,
            request=httpx.Request("GET", url),
        )

    def test_fetch_content_passes_cookies_to_httpx_get(self, monkeypatch):
        """httpx.get called inside fetch_content must carry the gateway cookies."""
        base_url = "https://connect.example.com"
        content_url = f"{base_url}/content/abc/"
        captured_kwargs: list[dict] = []

        def fake_get(url, **kwargs):
            captured_kwargs.append(kwargs)
            return self._make_response(200, url=url, body=b"ok")

        monkeypatch.setattr(httpx, "get", fake_get)

        jar = httpx.Cookies()
        jar.set("ptd_auth", "gw-tok", domain=".posit.team", path="/")

        client = ConnectClient(base_url=base_url, api_key="key", cookies=jar)
        client.fetch_content(content_url)

        assert captured_kwargs, "httpx.get was not called"
        passed_cookies = captured_kwargs[0].get("cookies")
        assert passed_cookies is not None, "cookies were not passed to httpx.get"
        if isinstance(passed_cookies, httpx.Cookies):
            assert passed_cookies.get("ptd_auth") == "gw-tok"
        else:
            # dict form
            assert passed_cookies.get("ptd_auth") == "gw-tok"
