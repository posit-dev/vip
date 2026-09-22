"""Tests for vip.auth module — auth cache load, save, and probing."""

from __future__ import annotations

import pytest


class TestSaveAuthCache:
    """_save_auth_cache must not poison the cache with failed mint attempts.

    When Connect is configured but key minting failed, api_key is None.
    Caching that state means subsequent runs short-circuit via the cache
    and never re-attempt the mint — the specific warning explaining why
    it failed is lost, and the user sees an opaque "set VIP_CONNECT_API_KEY"
    warning for 4 hours.
    """

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

    def test_writes_both_resolved_and_requested_connect_urls(self, tmp_path):
        """Save the pre-resolve form too so a later cache load can
        match against what the caller actually asked for, even when
        ``_resolve_connect_api_base`` rewrote the dashboard URL to a
        different API base.
        """
        import json

        from vip.auth import InteractiveAuthSession, _save_auth_cache

        state = tmp_path / "state.json"
        state.write_text('{"cookies": []}')
        session = InteractiveAuthSession(
            storage_state_path=state,
            api_key="REAL",
            key_name="_vip_interactive_1",
            _connect_url="https://c.example.com",
            _requested_connect_url="https://c.example.com/dashboard",
        )
        cache = tmp_path / ".vip-auth-cache.json"

        _save_auth_cache(session, cache)

        meta = json.loads(cache.with_suffix(".meta.json").read_text())
        assert meta["connect_url"] == "https://c.example.com"
        assert meta["requested_connect_url"] == "https://c.example.com/dashboard"


class TestLoadCachedAuth:
    """_load_cached_auth must refuse to reuse a cache that was minted
    against different product URLs.  The cache file lives one-per-
    checkout-directory, so reusing it across sites would silently send
    the wrong session cookies (and API key) to the new target.
    """

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
        Workbench test on stale state.  Treat as a miss.
        """
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
        must still hit the cache.
        """
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
        send stale storage state and API key to the wrong target.
        """
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

    def test_url_match_distinguishes_single_vs_double_trailing_slash(self, tmp_path):
        """``/app/`` and ``/app//`` are not guaranteed to route to the same
        handler.  Only a single trailing slash is treated as cosmetic;
        extra slashes are preserved so a misconfigured URL doesn't
        silently cache-hit against the canonical one.
        """
        from vip.auth import _load_cached_auth

        cache = self._write_cache(
            tmp_path,
            connect_url="https://connect.example.com/app/",
        )

        session = _load_cached_auth(
            cache,
            requested_connect_url="https://connect.example.com/app//",
            requested_workbench_url=None,
        )

        assert session is None

    def test_match_uses_requested_url_when_resolved_differs(self, tmp_path):
        """``_resolve_connect_api_base`` can rewrite the configured
        sub-path dashboard URL to a different API base.  Cache match
        must compare against what the caller asked for, not what
        Connect resolved it to — otherwise every run cache-misses for
        sub-path deployments.
        """
        import json
        from pathlib import Path as _Path

        from vip.auth import _load_cached_auth

        cache = _Path(tmp_path) / ".vip-auth-cache.json"
        cache.write_text('{"cookies": []}')
        cache.with_suffix(".meta.json").write_text(
            json.dumps(
                {
                    "api_key": "CACHED",
                    "key_name": "_vip_interactive_1",
                    "connect_url": "https://connect.example.com",
                    "requested_connect_url": "https://connect.example.com/dashboard",
                    "workbench_url": "",
                }
            )
        )

        session = _load_cached_auth(
            cache,
            requested_connect_url="https://connect.example.com/dashboard",
            requested_workbench_url=None,
        )

        assert session is not None
        assert session.api_key == "CACHED"
        # Resolved URL (used for API client + cleanup) is preserved.
        assert session._connect_url == "https://connect.example.com"
        # Requested URL (used for cache match) is also restored.
        assert session._requested_connect_url == "https://connect.example.com/dashboard"


def _jar(**cookies):
    """Build an httpx cookie jar for probe tests that don't care about scoping.

    The probe takes a jar rather than a flat dict so cookie domain/path survive;
    scoping itself is covered by TestProbeCookieScoping.
    """
    import httpx

    jar = httpx.Cookies()
    for name, value in cookies.items():
        jar.set(name, value, domain="w.example.com")
    return jar


class TestCookiesFromStorageState:
    """Playwright storage state is the only record of the cached browser
    session, so the liveness probe has to read cookies straight out of it.
    """

    @staticmethod
    def _write(tmp_path, payload):
        import json
        from pathlib import Path as _Path

        state = _Path(tmp_path) / ".vip-auth-cache.json"
        state.write_text(json.dumps(payload))
        return state

    def test_extracts_name_value_pairs(self, tmp_path):
        from vip.auth import _cookies_from_storage_state

        state = self._write(
            tmp_path,
            {
                "cookies": [
                    {"name": "rstudio-rs-csrf-token", "value": "abc", "domain": "w.example.com"},
                    {"name": "user-id", "value": "sam", "domain": "w.example.com"},
                ]
            },
        )

        jar = _cookies_from_storage_state(state)

        assert dict(jar) == {"rstudio-rs-csrf-token": "abc", "user-id": "sam"}
        # Scope must survive, or the probe cannot apply cookie matching.
        assert {c.domain for c in jar.jar} == {"w.example.com"}

    def test_returns_empty_for_state_without_cookies(self, tmp_path):
        from vip.auth import _cookies_from_storage_state

        assert len(_cookies_from_storage_state(self._write(tmp_path, {"origins": []})).jar) == 0

    def test_returns_empty_for_malformed_state(self, tmp_path):
        """A truncated cache file must not crash the run before any test executes."""
        from pathlib import Path as _Path

        from vip.auth import _cookies_from_storage_state

        state = _Path(tmp_path) / ".vip-auth-cache.json"
        state.write_text("{not json")

        assert len(_cookies_from_storage_state(state).jar) == 0

    def test_skips_cookies_missing_a_name(self, tmp_path):
        from vip.auth import _cookies_from_storage_state

        payload = {"cookies": [{"value": "orphan"}, {"name": "k", "value": "v"}]}
        state = self._write(tmp_path, payload)

        assert dict(_cookies_from_storage_state(state)) == {"k": "v"}


class TestCachedWorkbenchSessionIsLive:
    """The cached storage state can go stale long before the 4-hour TTL
    expires (the IdP session dies, or an admin invalidates it).  Without a
    liveness probe every Workbench test skips with a message that names no
    cause, because ``workbench_auth_error`` is only set on the fresh-auth
    path.  See issue: samcofer's 106-skip run.
    """

    def test_live_session_is_reported_live(self, tmp_path):
        import httpx

        from vip.auth import _cached_workbench_session_is_live

        def handler(request):
            return httpx.Response(200, text="<html>dashboard</html>")

        transport = httpx.MockTransport(handler)
        assert (
            _cached_workbench_session_is_live(
                "https://w.example.com", _jar(), transport=transport
            ).is_live
            is True
        )

    def test_redirect_to_sign_in_is_reported_dead(self, tmp_path):
        import httpx

        from vip.auth import _cached_workbench_session_is_live

        def handler(request):
            if "auth-sign-in" in str(request.url):
                return httpx.Response(200, text="<html>sign in</html>")
            return httpx.Response(302, headers={"Location": "/auth-sign-in?appUri=%2F"})

        transport = httpx.MockTransport(handler)
        assert (
            _cached_workbench_session_is_live(
                "https://w.example.com", _jar(), transport=transport
            ).is_live
            is False
        )

    @pytest.mark.parametrize("status", [401, 403])
    def test_unauthorized_without_redirect_is_reported_dead(self, status):
        """Some Workbench configs answer an expired session with a bare 401/403
        instead of redirecting, so the URL check alone would miss it.
        """
        import httpx

        from vip.auth import _cached_workbench_session_is_live

        transport = httpx.MockTransport(lambda request: httpx.Response(status))
        assert (
            _cached_workbench_session_is_live(
                "https://w.example.com", _jar(), transport=transport
            ).is_live
            is False
        )

    def test_transport_error_is_inconclusive_not_dead(self):
        """An unreachable deployment is not a dead session.  Failing closed here
        would force an interactive browser re-auth that cannot succeed either,
        and would bury the real reachability error.  Fail open and let the
        tests report the outage with their own message.
        """
        import httpx

        from vip.auth import _cached_workbench_session_is_live

        def boom(request):
            raise httpx.ConnectError("connection refused")

        transport = httpx.MockTransport(boom)
        assert (
            _cached_workbench_session_is_live(
                "https://w.example.com", _jar(), transport=transport
            ).is_live
            is None
        )


class TestLoadCachedAuthProbesWorkbench:
    @staticmethod
    def _write_cache(tmp_path, *, workbench_url: str, connect_url: str = ""):
        import json
        from pathlib import Path as _Path

        cache = _Path(tmp_path) / ".vip-auth-cache.json"
        cache.write_text('{"cookies": [{"name": "user-id", "value": "sam"}]}')
        cache.with_suffix(".meta.json").write_text(
            json.dumps(
                {
                    "api_key": "CACHED",
                    "key_name": "_vip_interactive_1",
                    "connect_url": connect_url,
                    "requested_connect_url": connect_url,
                    "workbench_url": workbench_url,
                }
            )
        )
        return cache

    def test_dead_workbench_session_is_a_cache_miss(self, tmp_path, capsys, monkeypatch):
        from vip import auth as auth_mod

        cache = self._write_cache(tmp_path, workbench_url="https://w.example.com")
        monkeypatch.setattr(
            auth_mod.cache,
            "_cached_workbench_session_is_live",
            lambda *a, **kw: auth_mod._ProbeResult(False, "Workbench answered 401"),
        )

        session = auth_mod._load_cached_auth(
            cache,
            requested_connect_url=None,
            requested_workbench_url="https://w.example.com",
        )

        assert session is None
        out = capsys.readouterr().out
        assert "Ignoring cached auth session" in out
        assert "no longer authenticates Workbench" in out

    def test_live_workbench_session_is_reused(self, tmp_path, monkeypatch):
        from vip import auth as auth_mod

        cache = self._write_cache(tmp_path, workbench_url="https://w.example.com")
        monkeypatch.setattr(
            auth_mod.cache,
            "_cached_workbench_session_is_live",
            lambda *a, **kw: auth_mod._ProbeResult(True),
        )

        session = auth_mod._load_cached_auth(
            cache,
            requested_connect_url=None,
            requested_workbench_url="https://w.example.com",
        )

        assert session is not None
        assert session.api_key == "CACHED"

    def test_inconclusive_probe_reuses_the_cache(self, tmp_path, monkeypatch):
        from vip import auth as auth_mod

        cache = self._write_cache(tmp_path, workbench_url="https://w.example.com")
        monkeypatch.setattr(
            auth_mod.cache,
            "_cached_workbench_session_is_live",
            lambda *a, **kw: auth_mod._ProbeResult(None, "could not reach Workbench"),
        )

        session = auth_mod._load_cached_auth(
            cache,
            requested_connect_url=None,
            requested_workbench_url="https://w.example.com",
        )

        assert session is not None

    def test_no_workbench_requested_skips_the_probe(self, tmp_path, monkeypatch):
        """Connect-only runs must not pay for a Workbench round-trip."""
        from vip import auth as auth_mod

        cache = self._write_cache(tmp_path, workbench_url="", connect_url="https://c.example.com")

        def boom(*a, **kw):
            raise AssertionError("probed Workbench on a Connect-only run")

        monkeypatch.setattr(auth_mod.cache, "_cached_workbench_session_is_live", boom)

        session = auth_mod._load_cached_auth(
            cache,
            requested_connect_url="https://c.example.com",
            requested_workbench_url=None,
        )

        assert session is not None

    def test_probe_receives_tls_settings(self, tmp_path, monkeypatch):
        """``--insecure`` / ``--ca-bundle`` deployments must not fail the probe on
        TLS and get sent through a pointless re-auth.
        """
        from vip import auth as auth_mod

        cache = self._write_cache(tmp_path, workbench_url="https://w.example.com")
        seen = {}

        def record(url, cookies, *, insecure=False, ca_bundle=None, transport=None, proxy=None):
            seen["insecure"] = insecure
            seen["ca_bundle"] = ca_bundle
            return auth_mod._ProbeResult(True)

        monkeypatch.setattr(auth_mod.cache, "_cached_workbench_session_is_live", record)

        auth_mod._load_cached_auth(
            cache,
            requested_connect_url=None,
            requested_workbench_url="https://w.example.com",
            insecure=True,
            ca_bundle=None,
        )

        assert seen == {"insecure": True, "ca_bundle": None}


class TestAuthCachePath:
    """``vip verify`` (plugin) and ``vip cleanup`` (CLI) must resolve the same
    cache file.  plugin.py used ``Path(config.rootpath)`` while cli.py used
    ``Path.cwd()``; for a uv-tool install pytest's rootdir is the common
    ancestor of cwd and site-packages, which lands in ``$HOME`` — so the two
    silently disagreed and ``vip cleanup`` looked in the wrong place.
    """

    def test_resolves_relative_to_the_invocation_directory(self, tmp_path, monkeypatch):
        from vip.auth import auth_cache_path

        monkeypatch.chdir(tmp_path)
        assert auth_cache_path() == tmp_path / ".vip-auth-cache.json"

    def test_call_sites_do_not_build_the_path_inline(self):
        """Invariant: the filename literal lives in one place.  A second inline
        copy is how the two call sites drifted apart in the first place.
        """
        from pathlib import Path as _Path

        import vip.auth.cache
        import vip.cli
        import vip.plugin

        for module in (vip.cli, vip.plugin):
            source = _Path(module.__file__).read_text()
            assert ".vip-auth-cache.json" not in source, (
                f"{module.__name__} builds the auth cache path inline; "
                "call vip.auth.auth_cache_path() instead"
            )

        assert ".vip-auth-cache.json" in _Path(vip.auth.cache.__file__).read_text()


class TestStaleCacheTriggersReauth:
    """End-to-end wiring: a dead cached session must fall through to the real
    auth flow, not be handed to the tests.  The helper-level tests above prove
    the probe verdict; this proves ``start_interactive_auth`` acts on it.
    """

    @staticmethod
    def _write_cache(tmp_path):
        import json
        from pathlib import Path as _Path

        cache = _Path(tmp_path) / ".vip-auth-cache.json"
        cache.write_text('{"cookies": [{"name": "user-id", "value": "sam"}]}')
        cache.with_suffix(".meta.json").write_text(
            json.dumps(
                {
                    "api_key": None,
                    "key_name": "",
                    "connect_url": "",
                    "requested_connect_url": "",
                    "workbench_url": "https://w.example.com",
                }
            )
        )
        return cache

    def test_dead_cache_falls_through_to_the_browser_flow(self, tmp_path, monkeypatch):
        from vip import auth as auth_mod

        cache = self._write_cache(tmp_path)
        monkeypatch.setattr(
            auth_mod.cache,
            "_cached_workbench_session_is_live",
            lambda *a, **kw: auth_mod._ProbeResult(False, "Workbench answered 401"),
        )

        reached = []

        def sentinel(*args, **kwargs):
            reached.append(True)
            raise RuntimeError("browser flow reached")

        monkeypatch.setattr(auth_mod.flows, "sync_playwright", sentinel)

        with pytest.raises(RuntimeError, match="browser flow reached"):
            auth_mod.start_interactive_auth(workbench_url="https://w.example.com", cache_path=cache)

        assert reached, "stale cache was reused instead of re-authenticating"

    def test_live_cache_short_circuits_the_browser_flow(self, tmp_path, monkeypatch):
        from vip import auth as auth_mod

        cache = self._write_cache(tmp_path)
        monkeypatch.setattr(
            auth_mod.cache,
            "_cached_workbench_session_is_live",
            lambda *a, **kw: auth_mod._ProbeResult(True),
        )

        def boom(*args, **kwargs):
            raise AssertionError("launched a browser despite a live cached session")

        monkeypatch.setattr(auth_mod.flows, "sync_playwright", boom)

        session = auth_mod.start_interactive_auth(
            workbench_url="https://w.example.com", cache_path=cache
        )

        assert session.storage_state_path == cache


class TestProbeCookieScoping:
    """The storage state is a whole browser context: the auth flow visits the
    IdP and Connect as well as Workbench, so the file holds cookies for all of
    them.  The probe must apply normal cookie scoping rather than firing every
    cookie at the Workbench host.
    """

    @staticmethod
    def _state(tmp_path, cookies):
        import json
        from pathlib import Path as _Path

        state = _Path(tmp_path) / ".vip-auth-cache.json"
        state.write_text(json.dumps({"cookies": cookies}))
        return state

    def _probe_and_capture(self, state, url):
        """Run the probe against *url* and return the Cookie header it sent."""
        import httpx

        from vip.auth import _cached_workbench_session_is_live, _cookies_from_storage_state

        sent = {}

        def handler(request):
            sent["cookie"] = request.headers.get("cookie", "")
            return httpx.Response(200, text="dashboard")

        _cached_workbench_session_is_live(
            url,
            _cookies_from_storage_state(state),
            transport=httpx.MockTransport(handler),
        )
        return sent["cookie"]

    def test_idp_cookies_are_not_sent_to_workbench(self, tmp_path):
        """Sending the IdP's session cookie to the Workbench host is unintended
        cross-host leakage; a browser would never do it.
        """
        state = self._state(
            tmp_path,
            [
                {"name": "wb-session", "value": "wb", "domain": "w.example.com", "path": "/"},
                {"name": "okta-sid", "value": "secret", "domain": "posit.okta.com", "path": "/"},
            ],
        )

        header = self._probe_and_capture(state, "https://w.example.com")

        assert "wb-session=wb" in header
        assert "okta-sid" not in header
        assert "secret" not in header

    def test_same_cookie_name_on_two_hosts_sends_the_workbench_value(self, tmp_path):
        """A flat name->value dict silently overwrites one host's cookie with
        another's.  Sending the IdP's value for a name Workbench also uses would
        make a *live* session read as dead and force a pointless re-auth.
        """
        state = self._state(
            tmp_path,
            [
                {"name": "session", "value": "workbench-value", "domain": "w.example.com"},
                {"name": "session", "value": "idp-value", "domain": "posit.okta.com"},
            ],
        )

        header = self._probe_and_capture(state, "https://w.example.com")

        assert "session=workbench-value" in header
        assert "idp-value" not in header

    def test_parent_domain_cookie_reaches_a_subdomain_host(self, tmp_path):
        """Leading-dot domains are host-suffix cookies and must still be sent,
        or a deployment sharing a parent domain would read as signed out.
        """
        state = self._state(
            tmp_path,
            [{"name": "shared", "value": "yes", "domain": ".example.com", "path": "/"}],
        )

        header = self._probe_and_capture(state, "https://w.example.com")

        assert "shared=yes" in header

    def test_path_scoping_is_respected(self, tmp_path):
        """A cookie scoped to an unrelated sub-path must not be sent to the root."""
        state = self._state(
            tmp_path,
            [
                {"name": "root", "value": "r", "domain": "w.example.com", "path": "/"},
                {"name": "deep", "value": "d", "domain": "w.example.com", "path": "/somewhere"},
            ],
        )

        header = self._probe_and_capture(state, "https://w.example.com/")

        assert "root=r" in header
        assert "deep" not in header


class TestProbeDetailNamesTheEvidence:
    """The cache-miss message quoted "sent back to the sign-in page" for every
    dead verdict, including bare 401/403 where no redirect happened.  A 401 and
    an expiry redirect point at different causes (a proxy stripping cookies vs a
    dead session), so the message has to name what was actually seen.
    """

    def test_sign_in_redirect_detail(self):
        import httpx

        from vip.auth import _cached_workbench_session_is_live

        def handler(request):
            if "auth-sign-in" in str(request.url):
                return httpx.Response(200, text="sign in")
            return httpx.Response(302, headers={"Location": "/auth-sign-in"})

        result = _cached_workbench_session_is_live(
            "https://w.example.com", httpx.Cookies(), transport=httpx.MockTransport(handler)
        )

        assert result.is_live is False
        assert "sign-in page" in result.detail

    @pytest.mark.parametrize("status", [401, 403])
    def test_unauthorized_detail_does_not_claim_a_redirect(self, status):
        import httpx

        from vip.auth import _cached_workbench_session_is_live

        result = _cached_workbench_session_is_live(
            "https://w.example.com",
            httpx.Cookies(),
            transport=httpx.MockTransport(lambda request: httpx.Response(status)),
        )

        assert result.is_live is False
        assert str(status) in result.detail
        assert "sign-in page" not in result.detail

    def test_cache_miss_message_quotes_the_detail(self, tmp_path, capsys, monkeypatch):
        import json

        from vip import auth as auth_mod

        cache = tmp_path / ".vip-auth-cache.json"
        cache.write_text('{"cookies": []}')
        cache.with_suffix(".meta.json").write_text(
            json.dumps({"api_key": None, "workbench_url": "https://w.example.com"})
        )
        monkeypatch.setattr(
            auth_mod.cache,
            "_cached_workbench_session_is_live",
            lambda *a, **kw: auth_mod._ProbeResult(False, "Workbench answered 401 Unauthorized"),
        )

        auth_mod._load_cached_auth(
            cache, requested_connect_url=None, requested_workbench_url="https://w.example.com"
        )

        out = capsys.readouterr().out
        assert "Workbench answered 401 Unauthorized" in out
        assert "sent back to the sign-in page" not in out


class TestRefreshAuthCacheFromStorageState:
    """A signed-out cache must be refreshable from a live browser context.

    ``test_workbench_signout`` ends the shared session, and
    ``restore_shared_session`` mints a fresh one *in the browser context* --
    but the on-disk cache still holds the cookies sign-out killed. Every
    subsequent ``vip verify`` then rejects the cache and re-authenticates
    interactively, popping a browser at the user. Refreshing the cache from
    the restored context closes that gap.
    """

    def _existing_cache(self, tmp_path):
        cache = tmp_path / ".vip-auth-cache.json"
        cache.write_text('{"cookies": [{"name": "dead", "value": "old"}], "origins": []}')
        cache.chmod(0o600)
        meta = cache.with_suffix(".meta.json")
        meta.write_text('{"api_key": null, "workbench_url": "https://wb.example.com"}')
        meta.chmod(0o600)
        return cache, meta

    def test_rewrites_an_existing_cache_with_the_live_state(self, tmp_path):
        import json

        from vip.auth import refresh_auth_cache_from_storage_state

        cache, meta = self._existing_cache(tmp_path)
        meta_before = meta.read_text()
        live = {"cookies": [{"name": "fresh", "value": "new"}], "origins": []}

        assert refresh_auth_cache_from_storage_state(live, cache) is True
        assert json.loads(cache.read_text()) == live
        # The companion metadata (api key, URLs) is unrelated to session
        # liveness and must survive untouched.
        assert meta.read_text() == meta_before

    def test_keeps_owner_only_permissions(self, tmp_path):
        import stat

        from vip.auth import refresh_auth_cache_from_storage_state

        cache, _ = self._existing_cache(tmp_path)

        refresh_auth_cache_from_storage_state({"cookies": [], "origins": []}, cache)

        mode = stat.S_IMODE(cache.stat().st_mode)
        assert mode == 0o600, f"session cookies must stay owner-only, got {oct(mode)}"

    def test_does_not_create_a_cache_that_did_not_exist(self, tmp_path):
        """No cache means no `--interactive-auth` run to refresh; stay out of it."""
        from vip.auth import refresh_auth_cache_from_storage_state

        cache = tmp_path / ".vip-auth-cache.json"

        assert refresh_auth_cache_from_storage_state({"cookies": []}, cache) is False
        assert not cache.exists()

    def test_leaves_no_temp_file_behind(self, tmp_path):
        from vip.auth import refresh_auth_cache_from_storage_state

        cache, _ = self._existing_cache(tmp_path)

        refresh_auth_cache_from_storage_state({"cookies": [], "origins": []}, cache)

        assert sorted(p.name for p in tmp_path.iterdir()) == [
            ".vip-auth-cache.json",
            ".vip-auth-cache.meta.json",
        ]

    def test_never_raises_when_the_state_is_not_serialisable(self, tmp_path):
        """Cleanup-path helper: a bad value must not blow up a passing test."""
        from vip.auth import refresh_auth_cache_from_storage_state

        cache, _ = self._existing_cache(tmp_path)
        before = cache.read_text()

        assert refresh_auth_cache_from_storage_state({"cookies": object()}, cache) is False
        assert cache.read_text() == before, "a failed refresh must leave the cache intact"
