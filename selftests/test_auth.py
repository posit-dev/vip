"""Tests for vip.auth module — headless auth validation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from vip.auth import (
    AuthConfigError,
    InteractiveAuthSession,
    authenticated_page,
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

    def test_writes_both_resolved_and_requested_connect_urls(self, tmp_path):
        """Save the pre-resolve form too so a later cache load can
        match against what the caller actually asked for, even when
        ``_resolve_connect_api_base`` rewrote the dashboard URL to a
        different API base."""
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


class TestStartInteractiveAuthPollLoop:
    """start_interactive_auth() launches a headed browser and blocks on an
    INLINE poll loop (auth.py ~437-470) waiting for a human to complete
    login through the IdP.  This loop is separate from the headless
    ``_wait_for_product_redirect`` helper that ``start_headless_auth`` uses
    (see ``TestWaitForProductRedirect`` below) — it has its own
    success/timeout detection that previously had no direct test.  These
    tests pin that detection down with no real browser or wall-clock wait.
    """

    @staticmethod
    def _make_playwright_stub(urls: list[str]) -> MagicMock:
        """Stub sync_playwright() so ``page.url`` yields *urls* in order,
        then repeats the last value once exhausted. ``page.wait_for_timeout``
        is a no-op so the loop iterates instantly."""

        class _PageStub:
            def __init__(self, urls: list[str]):
                self._urls = list(urls)

            @property
            def url(self) -> str:
                if len(self._urls) > 1:
                    return self._urls.pop(0)
                return self._urls[0]

            def goto(self, *_args, **_kwargs) -> None:
                return None

            def wait_for_timeout(self, *_args, **_kwargs) -> None:
                return None

        pw = MagicMock()
        browser = pw.start.return_value.chromium.launch.return_value
        browser.new_context.return_value.new_page.return_value = _PageStub(urls)
        return pw

    def test_connect_login_completes_once_login_path_is_left(self, monkeypatch):
        """Connect: login is detected once the URL contains the base URL
        and no longer contains ``/__login__``."""
        from vip.auth import start_interactive_auth

        stub = self._make_playwright_stub(
            [
                "https://connect.example.com/__login__",
                "https://connect.example.com/",
            ]
        )
        monkeypatch.setattr("vip.auth.sync_playwright", lambda: stub)
        monkeypatch.setattr("vip.auth._resolve_connect_api_base", lambda *a, **kw: a[0])
        monkeypatch.setattr("vip.auth._create_api_key_via_session", lambda *a, **kw: "FAKE_KEY")

        session = start_interactive_auth(connect_url="https://connect.example.com")

        assert session.api_key == "FAKE_KEY"

    def test_workbench_only_login_completes_off_signin_page(self, monkeypatch):
        """Workbench-only: login is detected once the URL is on the base
        URL and is NOT a page whose URL contains sign-in/login/auth."""
        from vip.auth import start_interactive_auth

        stub = self._make_playwright_stub(
            [
                "https://wb.example.com/auth-sign-in",
                "https://wb.example.com/",
            ]
        )
        monkeypatch.setattr("vip.auth.sync_playwright", lambda: stub)

        session = start_interactive_auth(workbench_url="https://wb.example.com")

        assert session.api_key is None
        assert session._workbench_url == "https://wb.example.com"

    def test_timeout_raises_runtime_error(self, monkeypatch):
        """If the URL never satisfies the completion condition before the
        deadline, the loop must raise RuntimeError rather than continue
        or return silently."""
        from vip import auth as auth_mod

        stub = self._make_playwright_stub(["https://wb.example.com/auth-sign-in"])
        monkeypatch.setattr(auth_mod, "sync_playwright", lambda: stub)

        # First call computes the deadline, second is the loop's own
        # `while time.monotonic() < deadline` check — make it already
        # expired so the loop body never runs and page.url is never read.
        times = iter([0.0, 1000.0])
        monkeypatch.setattr(auth_mod.time, "monotonic", lambda: next(times))

        with pytest.raises(RuntimeError, match="did not complete within 5 minutes"):
            auth_mod.start_interactive_auth(workbench_url="https://wb.example.com")


class TestStartInteractiveAuthSchemeResolutionWiring:
    """*_scheme_inferred flags gate calls to resolve_url_scheme (issue #537):
    an explicit scheme must never be second-guessed, and an inferred one
    must be resolved before Playwright or the mint client touch the URL."""

    @staticmethod
    def _playwright_stub(logged_in_url: str) -> MagicMock:
        """Stub sync_playwright() whose page is immediately "logged in" at
        *logged_in_url* (must match the resolved primary_url + no /__login__)."""

        class _PageStub:
            url = logged_in_url

            def goto(self, *_a, **_kw) -> None:
                return None

            def wait_for_timeout(self, *_a, **_kw) -> None:
                return None

        pw = MagicMock()
        browser = pw.start.return_value.chromium.launch.return_value
        browser.new_context.return_value.new_page.return_value = _PageStub()
        return pw

    def test_inferred_scheme_is_resolved_before_use(self, monkeypatch):
        """A downgrade must reach both the browser (page.goto) and the mint
        client -- not just one of the two."""
        from vip.auth import start_interactive_auth

        monkeypatch.setattr(
            "vip.auth.sync_playwright",
            lambda: self._playwright_stub("http://connect.example.com/"),
        )
        monkeypatch.setattr("vip.auth._resolve_connect_api_base", lambda *a, **kw: a[0])
        mint = MagicMock(return_value="FAKE_KEY")
        monkeypatch.setattr("vip.auth._create_api_key_via_session", mint)
        resolve = MagicMock(return_value="http://connect.example.com")
        monkeypatch.setattr("vip.auth.resolve_url_scheme", resolve)

        session = start_interactive_auth(
            connect_url="https://connect.example.com",
            connect_url_scheme_inferred=True,
        )

        resolve.assert_called_once()
        called_pc = resolve.call_args.args[0]
        assert called_pc.url == "https://connect.example.com"
        assert called_pc.url_scheme_inferred is True
        assert resolve.call_args.kwargs == {"insecure": False, "ca_bundle": None}
        assert session._connect_url == "http://connect.example.com"
        # The mint client must have been called with the resolved URL, not
        # the original https:// one.
        assert mint.call_args.args[1] == "http://connect.example.com"

    def test_explicit_scheme_never_probes(self, monkeypatch):
        """A user-supplied scheme is authoritative -- no probe, ever.

        resolve_url_scheme is *not* mocked here: it is always called (that's
        the point of taking the whole ProductConfig -- see its docstring),
        but for an explicit scheme its own internal check must make that a
        no-op. Mocking httpx.get directly (the actual network boundary)
        proves that no-op is real, not an artifact of also mocking the
        function meant to enforce it.
        """
        from vip.auth import start_interactive_auth

        monkeypatch.setattr(
            "vip.auth.sync_playwright",
            lambda: self._playwright_stub("https://connect.example.com/"),
        )
        monkeypatch.setattr("vip.auth._resolve_connect_api_base", lambda *a, **kw: a[0])
        monkeypatch.setattr("vip.auth._create_api_key_via_session", lambda *a, **kw: "FAKE_KEY")

        with patch("httpx.get") as mock_get:
            session = start_interactive_auth(
                connect_url="https://connect.example.com",
                connect_url_scheme_inferred=False,
            )

        mock_get.assert_not_called()
        assert session._connect_url == "https://connect.example.com"

    def test_default_is_not_inferred(self, monkeypatch):
        """The *_scheme_inferred parameters default to False so a caller that
        doesn't pass them (e.g. an older test or script) keeps today's
        behaviour: no probing."""
        from vip.auth import start_interactive_auth

        monkeypatch.setattr(
            "vip.auth.sync_playwright",
            lambda: self._playwright_stub("https://connect.example.com/"),
        )
        monkeypatch.setattr("vip.auth._resolve_connect_api_base", lambda *a, **kw: a[0])
        monkeypatch.setattr("vip.auth._create_api_key_via_session", lambda *a, **kw: "FAKE_KEY")

        with patch("httpx.get") as mock_get:
            start_interactive_auth(connect_url="https://connect.example.com")

        mock_get.assert_not_called()


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
        assert resolve.call_args.kwargs == {"insecure": False, "ca_bundle": None}
        assert session._connect_url == "http://connect.example.com"
        assert mint.call_args.args[1] == "http://connect.example.com"

    def test_explicit_scheme_never_probes(self, monkeypatch):
        """See the interactive-auth counterpart's docstring: resolve_url_scheme
        is always called, but must no-op on its own for an explicit scheme --
        proved here by mocking httpx.get (the real network boundary) rather
        than resolve_url_scheme itself."""
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


class TestSchemeResolutionRealCodePath:
    """Regression coverage proving the explicit-scheme invariant through the
    actual production path -- ``vip.config.load_config`` all the way to
    ``start_interactive_auth`` -- rather than a hand-typed
    ``url_scheme_inferred`` in an isolated unit test.

    A type-design review on #562 called out that a test which sets
    ``url_scheme_inferred=False`` (or constructs a mock with it) by hand only
    proves the function behaves given that input; it says nothing about
    whether a real caller ever produces that input correctly. These tests
    load a real ``vip.toml`` through ``load_config`` -- the same code every
    ``vip verify`` invocation runs -- and mock only ``httpx.get`` (the actual
    network boundary) plus Playwright (no real browser in a selftest), so a
    regression in how provenance is computed or threaded through would fail
    here even if every unit test above still passed.
    """

    @staticmethod
    def _playwright_stub(logged_in_url: str) -> MagicMock:
        class _PageStub:
            url = logged_in_url

            def goto(self, *_a, **_kw) -> None:
                return None

            def wait_for_timeout(self, *_a, **_kw) -> None:
                return None

        pw = MagicMock()
        browser = pw.start.return_value.chromium.launch.return_value
        browser.new_context.return_value.new_page.return_value = _PageStub()
        return pw

    def test_explicit_scheme_from_real_config_never_probes(self, tmp_toml, monkeypatch):
        from vip.auth import start_interactive_auth
        from vip.config import load_config

        path = tmp_toml('[connect]\nurl = "https://connect.example.com"\n')
        cfg = load_config(path)
        assert cfg.connect.url_scheme_inferred is False  # real provenance, not hand-set

        monkeypatch.setattr(
            "vip.auth.sync_playwright",
            lambda: self._playwright_stub("https://connect.example.com/"),
        )
        monkeypatch.setattr("vip.auth._resolve_connect_api_base", lambda *a, **kw: a[0])
        monkeypatch.setattr("vip.auth._create_api_key_via_session", lambda *a, **kw: "FAKE_KEY")

        with patch("httpx.get") as mock_get:
            session = start_interactive_auth(
                connect_url=cfg.connect.url,
                connect_url_scheme_inferred=cfg.connect.url_scheme_inferred,
            )

        mock_get.assert_not_called()
        assert session._connect_url == "https://connect.example.com"

    def test_inferred_scheme_from_real_config_falls_back_when_unreachable(
        self, tmp_toml, monkeypatch
    ):
        """Same real load_config path, but scheme-less -- proves the other
        half of the invariant end-to-end too: an inferred scheme really does
        get probed and can fall back, driven by the real provenance value."""
        from vip.auth import start_interactive_auth
        from vip.config import load_config

        path = tmp_toml('[connect]\nurl = "connect.example.com"\n')
        cfg = load_config(path)
        assert cfg.connect.url_scheme_inferred is True

        monkeypatch.setattr(
            "vip.auth.sync_playwright",
            lambda: self._playwright_stub("http://connect.example.com/"),
        )
        monkeypatch.setattr("vip.auth._resolve_connect_api_base", lambda *a, **kw: a[0])
        monkeypatch.setattr("vip.auth._create_api_key_via_session", lambda *a, **kw: "FAKE_KEY")

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")):
            session = start_interactive_auth(
                connect_url=cfg.connect.url,
                connect_url_scheme_inferred=cfg.connect.url_scheme_inferred,
            )

        assert session._connect_url == "http://connect.example.com"


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

    def test_timeout_reason_strips_oidc_query_parameters(self, monkeypatch):
        """The returned URL is surfaced in CI logs via the workbench skip
        message.  OIDC/SAML redirects can carry ``code=``, ``state=``,
        and ``SAMLRequest=`` query parameters — sensitive auth artifacts
        that must not leak.  Path is preserved so the failure is still
        debuggable."""
        from unittest.mock import PropertyMock

        from vip import auth as auth_mod

        page = MagicMock()
        page.goto.return_value = None
        page.wait_for_load_state.return_value = None
        type(page).url = PropertyMock(
            return_value=(
                "https://idp.example.com/sso/callback?code=AUTH_CODE_SECRET&state=STATE_TOKEN"
            )
        )

        times = iter([0.0, 1000.0])
        monkeypatch.setattr(auth_mod.time, "monotonic", lambda: next(times))

        result = auth_mod._authenticate_workbench(page, "https://wb.example.com")

        assert result is not None
        assert "AUTH_CODE_SECRET" not in result
        assert "STATE_TOKEN" not in result
        assert "code=" not in result
        assert "state=" not in result
        assert "/sso/callback" in result


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

    def test_url_match_distinguishes_single_vs_double_trailing_slash(self, tmp_path):
        """``/app/`` and ``/app//`` are not guaranteed to route to the same
        handler.  Only a single trailing slash is treated as cosmetic;
        extra slashes are preserved so a misconfigured URL doesn't
        silently cache-hit against the canonical one."""
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
        sub-path deployments."""
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


class TestResolveUrlScheme:
    """resolve_url_scheme falls an inferred https:// URL back to http:// only
    when https genuinely doesn't answer (issue #537).

    Every test builds a real ``ConnectConfig``/``ProductConfig`` (never a
    hand-set ``url_scheme_inferred``) so the "explicit scheme" cases run
    through the actual provenance computation in ``vip.config._normalize_url``,
    not a value a test author typed by hand. A type-design review on #562
    flagged that ``resolve_url_scheme`` used to take a bare ``url: str`` and
    trust the caller to have checked ``url_scheme_inferred`` first -- a
    forgotten check was invisible. It now takes the ``ProductConfig`` itself
    and consults provenance internally, so there is no bare-string entry
    point left for a caller (or a test) to accidentally skip that check.

    Every test clears the module-level cache first so results from one test
    don't leak into the next -- the whole point of the cache is to survive
    across calls *within* a run, not across independent test cases.

    ``_tls_listener_present`` is patched to ``False`` by default for every
    test in this class (a real TCP connect to a fake ``connect.example.com``
    would otherwise depend on DNS/network behavior in whatever environment
    runs the suite -- see ``test_auth_tls_e2e.py`` for the real-socket
    version of this proof against an actual listener). Tests for the
    "TLS present but untrusted" branch override it locally to ``True``.
    """

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        import vip.auth

        vip.auth._scheme_resolution_cache.clear()
        yield
        vip.auth._scheme_resolution_cache.clear()

    @pytest.fixture(autouse=True)
    def _no_real_tls_listener(self):
        with patch("vip.auth._tls_listener_present", return_value=False):
            yield

    @staticmethod
    def _pc(url: str):
        from vip.config import ConnectConfig

        return ConnectConfig(url=url)

    def test_explicit_http_never_probed(self):
        """An explicit http:// is authoritative -- never probed, never
        upgraded."""
        from vip.auth import resolve_url_scheme

        pc = self._pc("http://connect.example.com")
        assert pc.url_scheme_inferred is False

        with patch("httpx.get") as mock_get:
            result = resolve_url_scheme(pc)

        assert result == "http://connect.example.com"
        mock_get.assert_not_called()

    def test_explicit_https_never_probed(self):
        """An explicit https:// is authoritative -- never probed, even if it
        would otherwise be unreachable. This is the case the type-design
        review specifically flagged: swap the mock below for a ConnectError
        and the assertion must still hold, because provenance (not the
        prefix or a mock's success) is what gates the probe."""
        from vip.auth import resolve_url_scheme

        pc = self._pc("https://connect.example.com")
        assert pc.url_scheme_inferred is False

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")) as mock_get:
            result = resolve_url_scheme(pc)

        assert result == "https://connect.example.com"
        mock_get.assert_not_called()

    def test_https_that_answers_is_kept(self):
        """https:// responds (any status) -- kept as-is, nothing downgraded."""
        from vip.auth import resolve_url_scheme

        pc = self._pc("connect.example.com")
        assert pc.url_scheme_inferred is True

        with patch("httpx.get", return_value=MagicMock(status_code=200)):
            result = resolve_url_scheme(pc)

        assert result == "https://connect.example.com"

    def test_https_5xx_is_not_a_fallback_trigger(self):
        """A 500 means the server answered -- do not fall back to http://."""
        from vip.auth import resolve_url_scheme

        pc = self._pc("connect.example.com")

        with patch("httpx.get", return_value=MagicMock(status_code=500)):
            result = resolve_url_scheme(pc)

        assert result == "https://connect.example.com"

    def test_connection_failure_falls_back_to_http(self):
        """A connection-level failure (refused, DNS, TLS, timeout) -- the
        server genuinely doesn't answer -- triggers the http:// fallback."""
        from vip.auth import resolve_url_scheme

        pc = self._pc("connect.example.com")

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")):
            result = resolve_url_scheme(pc)

        assert result == "http://connect.example.com"

    def test_timeout_falls_back_to_http(self):
        """ConnectTimeout is also a TransportError -- same fallback."""
        from vip.auth import resolve_url_scheme

        pc = self._pc("connect.example.com")

        with patch("httpx.get", side_effect=httpx.ConnectTimeout("timed out")):
            result = resolve_url_scheme(pc)

        assert result == "http://connect.example.com"

    def test_fallback_is_logged_loudly(self, capsys):
        """A user who meant https must see that they got plaintext instead."""
        from vip.auth import resolve_url_scheme

        pc = self._pc("connect.example.com")

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")):
            resolve_url_scheme(pc)

        out = capsys.readouterr().out
        assert "connect.example.com" in out
        assert "http://connect.example.com" in out

    def test_success_is_not_logged(self, capsys):
        """Keeping https (the common case) must not print a warning."""
        from vip.auth import resolve_url_scheme

        pc = self._pc("connect.example.com")

        with patch("httpx.get", return_value=MagicMock(status_code=200)):
            resolve_url_scheme(pc)

        assert capsys.readouterr().out == ""

    def test_mutates_pc_in_place_and_resets_inferred_flag(self):
        """After resolving, pc.url holds the final value and
        pc.url_scheme_inferred is reset to False -- resolution is a one-time
        transition, not a repeatable state a second call re-enters."""
        from vip.auth import resolve_url_scheme

        pc = self._pc("connect.example.com")

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")):
            resolve_url_scheme(pc)

        assert pc.url == "http://connect.example.com"
        assert pc.url_scheme_inferred is False

    def test_second_call_on_same_pc_is_a_pure_read_no_probe(self):
        """Once url_scheme_inferred is reset, a second call on the *same*
        ProductConfig must not touch the network at all -- not even a cache
        lookup is needed, since the flag itself now says "nothing to do"."""
        from vip.auth import resolve_url_scheme

        pc = self._pc("connect.example.com")

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")) as mock_get:
            first = resolve_url_scheme(pc)
            second = resolve_url_scheme(pc)

        assert first == second == "http://connect.example.com"
        mock_get.assert_called_once()

    def test_result_is_cached_across_different_pc_instances(self):
        """A *different* ProductConfig for the same URL (e.g. a fresh
        instance built from the same --connect-url at another call site)
        still only probes once, via the module-level cache."""
        from vip.auth import resolve_url_scheme

        pc1 = self._pc("connect.example.com")
        pc2 = self._pc("connect.example.com")

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")) as mock_get:
            first = resolve_url_scheme(pc1)
            second = resolve_url_scheme(pc2)

        assert first == second == "http://connect.example.com"
        mock_get.assert_called_once()

    def test_probe_uses_follow_redirects_and_verify(self, tmp_path):
        """The probe itself must honour insecure/ca_bundle and follow
        redirects, matching every other httpx call site in this module."""
        from vip.auth import resolve_url_scheme

        ca = tmp_path / "ca.pem"
        pc = self._pc("connect.example.com")
        with patch("httpx.get", return_value=MagicMock(status_code=200)) as mock_get:
            resolve_url_scheme(pc, ca_bundle=ca)

        assert mock_get.call_args.kwargs["follow_redirects"] is True
        assert mock_get.call_args.kwargs["verify"] == str(ca)

    def test_tls_present_but_untrusted_does_not_downgrade(self):
        """When a real listener is present (a TLS-level failure, not a
        transport-level one) but the connection still failed with a
        TransportError -- e.g. a self-signed cert -- resolve_url_scheme
        must NOT downgrade to http://. Downgrading here would send
        credentials to a real TLS-terminating server in the clear. See
        test_auth_tls_e2e.py for the same proof against a real self-signed
        listener rather than this mock."""
        from vip.auth import resolve_url_scheme

        pc = self._pc("connect.example.com")

        with patch("vip.auth._tls_listener_present", return_value=True):
            with patch(
                "httpx.get",
                side_effect=httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]"),
            ):
                result = resolve_url_scheme(pc)

        assert result == "https://connect.example.com"
        assert pc.url == "https://connect.example.com"
        assert pc.url_scheme_inferred is False  # settled as https, not left ambiguous

    def test_tls_present_but_untrusted_names_the_remedy(self, capsys):
        """The warning for this case must be distinguishable from the
        "nothing answered" warning and must name the actual fix -- silently
        printing the same generic message as the network-unreachable case
        would leave a user with an untrusted cert no better off."""
        from vip.auth import resolve_url_scheme

        pc = self._pc("connect.example.com")

        with patch("vip.auth._tls_listener_present", return_value=True):
            with patch("httpx.get", side_effect=httpx.ConnectError("nope")):
                resolve_url_scheme(pc)

        out = capsys.readouterr().out
        assert "NOT falling back to plaintext" in out
        assert "insecure" in out
        assert "ca_bundle" in out
        # Must not also claim the server "did not answer" -- it did, just not
        # with a certificate this client trusts.
        assert "did not answer" not in out

    def test_result_is_cached_per_url_and_tls_settings(self):
        """Two calls with the same URL but different insecure/ca_bundle must
        each probe -- a cached verify=True failure must not authorise a
        downgrade decision for a caller that actually passed a different
        TLS configuration and might get a different, correct answer."""
        from vip.auth import resolve_url_scheme

        pc1 = self._pc("connect.example.com")
        pc2 = self._pc("connect.example.com")

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")) as mock_get:
            resolve_url_scheme(pc1, insecure=False)
            resolve_url_scheme(pc2, insecure=True)

        assert mock_get.call_count == 2

    def test_same_url_and_tls_settings_still_share_the_cache(self):
        """The cache-keying fix must not regress the existing dedup: two
        different ProductConfig instances with the same URL *and* the same
        insecure/ca_bundle still cost only one probe."""
        from vip.auth import resolve_url_scheme

        pc1 = self._pc("connect.example.com")
        pc2 = self._pc("connect.example.com")

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")) as mock_get:
            resolve_url_scheme(pc1, insecure=False)
            resolve_url_scheme(pc2, insecure=False)

        mock_get.assert_called_once()


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

    def test_follows_redirects(self):
        """follow_redirects=True must be set so an http->https (or trailing-
        slash) redirect isn't treated as a mint failure (issue #537).
        Matches _resolve_connect_api_base's probes, which already do this."""
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


class TestAuthenticatedPage:
    """Tests for authenticated_page(): the CLI cleanup escape hatch's
    browser-driven Workbench UI access (see vip.cli.run_cleanup)."""

    def _make_session(self, tmp_path) -> InteractiveAuthSession:
        state_path = tmp_path / "vip-auth-state.json"
        state_path.write_text('{"cookies": []}')
        return InteractiveAuthSession(storage_state_path=state_path, _tmpdir="")

    def test_loads_storage_state_and_yields_page(self, tmp_path):
        session = self._make_session(tmp_path)

        pw = MagicMock()
        browser = pw.start.return_value.chromium.launch.return_value
        context = browser.new_context.return_value
        page = context.new_page.return_value

        with patch("vip.auth.sync_playwright", return_value=pw):
            with authenticated_page(session) as yielded_page:
                assert yielded_page is page

        browser.new_context.assert_called_once_with(
            storage_state=str(session.storage_state_path),
            ignore_https_errors=False,
        )
        context.close.assert_called_once()
        browser.close.assert_called_once()
        pw.start.return_value.stop.assert_called_once()

    def test_insecure_passed_through_to_new_context(self, tmp_path):
        session = self._make_session(tmp_path)

        pw = MagicMock()
        browser = pw.start.return_value.chromium.launch.return_value
        context = browser.new_context.return_value

        with patch("vip.auth.sync_playwright", return_value=pw):
            with authenticated_page(session, insecure=True):
                pass

        _, kwargs = browser.new_context.call_args
        assert kwargs["ignore_https_errors"] is True
        context.close.assert_called_once()

    def test_closes_browser_and_context_even_when_block_raises(self, tmp_path):
        session = self._make_session(tmp_path)

        pw = MagicMock()
        browser = pw.start.return_value.chromium.launch.return_value
        context = browser.new_context.return_value

        with patch("vip.auth.sync_playwright", return_value=pw):
            with pytest.raises(RuntimeError, match="boom"):
                with authenticated_page(session):
                    raise RuntimeError("boom")

        context.close.assert_called_once()
        browser.close.assert_called_once()
        pw.start.return_value.stop.assert_called_once()

    def test_ca_bundle_sets_and_restores_node_extra_ca_certs(self, tmp_path, monkeypatch):
        import os

        monkeypatch.delenv("NODE_EXTRA_CA_CERTS", raising=False)
        session = self._make_session(tmp_path)
        ca_file = tmp_path / "ca.pem"
        ca_file.write_text("# fake CA")

        captured: list[str | None] = []

        pw = MagicMock()

        def capturing_launch(*args, **kwargs):
            captured.append(os.environ.get("NODE_EXTRA_CA_CERTS"))
            return pw.start.return_value.chromium.launch.return_value

        pw.start.return_value.chromium.launch.side_effect = capturing_launch

        with patch("vip.auth.sync_playwright", return_value=pw):
            with authenticated_page(session, ca_bundle=ca_file):
                pass

        assert captured == [str(ca_file)]
        assert os.environ.get("NODE_EXTRA_CA_CERTS") is None


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
    session, so the liveness probe has to read cookies straight out of it."""

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
    path.  See issue: samcofer's 106-skip run."""

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
        instead of redirecting, so the URL check alone would miss it."""
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
        tests report the outage with their own message."""
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
            auth_mod,
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
            auth_mod,
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
            auth_mod,
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

        monkeypatch.setattr(auth_mod, "_cached_workbench_session_is_live", boom)

        session = auth_mod._load_cached_auth(
            cache,
            requested_connect_url="https://c.example.com",
            requested_workbench_url=None,
        )

        assert session is not None

    def test_probe_receives_tls_settings(self, tmp_path, monkeypatch):
        """``--insecure`` / ``--ca-bundle`` deployments must not fail the probe on
        TLS and get sent through a pointless re-auth."""
        from vip import auth as auth_mod

        cache = self._write_cache(tmp_path, workbench_url="https://w.example.com")
        seen = {}

        def record(url, cookies, *, insecure=False, ca_bundle=None, transport=None):
            seen["insecure"] = insecure
            seen["ca_bundle"] = ca_bundle
            return auth_mod._ProbeResult(True)

        monkeypatch.setattr(auth_mod, "_cached_workbench_session_is_live", record)

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
    silently disagreed and ``vip cleanup`` looked in the wrong place."""

    def test_resolves_relative_to_the_invocation_directory(self, tmp_path, monkeypatch):
        from vip.auth import auth_cache_path

        monkeypatch.chdir(tmp_path)
        assert auth_cache_path() == tmp_path / ".vip-auth-cache.json"

    def test_call_sites_do_not_build_the_path_inline(self):
        """Invariant: the filename literal lives in one place.  A second inline
        copy is how the two call sites drifted apart in the first place."""
        from pathlib import Path as _Path

        import vip.auth
        import vip.cli
        import vip.plugin

        for module in (vip.cli, vip.plugin):
            source = _Path(module.__file__).read_text()
            assert ".vip-auth-cache.json" not in source, (
                f"{module.__name__} builds the auth cache path inline; "
                "call vip.auth.auth_cache_path() instead"
            )

        assert ".vip-auth-cache.json" in _Path(vip.auth.__file__).read_text()


class TestStaleCacheTriggersReauth:
    """End-to-end wiring: a dead cached session must fall through to the real
    auth flow, not be handed to the tests.  The helper-level tests above prove
    the probe verdict; this proves ``start_interactive_auth`` acts on it."""

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
            auth_mod,
            "_cached_workbench_session_is_live",
            lambda *a, **kw: auth_mod._ProbeResult(False, "Workbench answered 401"),
        )

        reached = []

        def sentinel(*args, **kwargs):
            reached.append(True)
            raise RuntimeError("browser flow reached")

        monkeypatch.setattr(auth_mod, "sync_playwright", sentinel)

        with pytest.raises(RuntimeError, match="browser flow reached"):
            auth_mod.start_interactive_auth(workbench_url="https://w.example.com", cache_path=cache)

        assert reached, "stale cache was reused instead of re-authenticating"

    def test_live_cache_short_circuits_the_browser_flow(self, tmp_path, monkeypatch):
        from vip import auth as auth_mod

        cache = self._write_cache(tmp_path)
        monkeypatch.setattr(
            auth_mod,
            "_cached_workbench_session_is_live",
            lambda *a, **kw: auth_mod._ProbeResult(True),
        )

        def boom(*args, **kwargs):
            raise AssertionError("launched a browser despite a live cached session")

        monkeypatch.setattr(auth_mod, "sync_playwright", boom)

        session = auth_mod.start_interactive_auth(
            workbench_url="https://w.example.com", cache_path=cache
        )

        assert session.storage_state_path == cache


class TestProbeCookieScoping:
    """The storage state is a whole browser context: the auth flow visits the
    IdP and Connect as well as Workbench, so the file holds cookies for all of
    them.  The probe must apply normal cookie scoping rather than firing every
    cookie at the Workbench host."""

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
        cross-host leakage; a browser would never do it."""
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
        make a *live* session read as dead and force a pointless re-auth."""
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
        or a deployment sharing a parent domain would read as signed out."""
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
    dead session), so the message has to name what was actually seen."""

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
            auth_mod,
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
        import os

        cache = tmp_path / ".vip-auth-cache.json"
        cache.write_text('{"cookies": [{"name": "dead", "value": "old"}], "origins": []}')
        os.chmod(cache, 0o600)
        meta = cache.with_suffix(".meta.json")
        meta.write_text('{"api_key": null, "workbench_url": "https://wb.example.com"}')
        os.chmod(meta, 0o600)
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
