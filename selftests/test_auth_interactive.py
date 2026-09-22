"""Tests for vip.auth module — interactive auth session lifecycle."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from vip.auth import (
    InteractiveAuthSession,
    authenticated_page,
)


class TestInteractiveAuthSessionCleanup:
    """Cleanup must not delete an API key that the on-disk cache still
    references.  Otherwise run 1 mints K, writes cache(K), then deletes
    K at cleanup — run 2 loads cache(K), tries to authenticate, 401s.
    Orphan cleanup at the next mint (via ``_delete_stale_vip_keys``)
    reaps keys older than :data:`_ORPHAN_MIN_AGE_SECONDS`.
    """

    def _session_with_cache(self, tmp_path, *, api_key: str, cache_key: str | None):
        """Return a session whose ``_cache_path`` points at a cache whose
        meta.json holds ``cache_key`` (or no cache file at all if None).
        """
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
        Next run will cache-hit and reuse the same key successfully.
        """
        session, _ = self._session_with_cache(tmp_path, api_key="LIVE", cache_key="LIVE")

        with patch("vip.auth._delete_api_key") as deleter:
            session.cleanup()

        deleter.assert_not_called()

    def test_deletes_when_cache_file_is_missing(self, tmp_path):
        """No cache on disk → no future run will reference this key → delete it
        now so we don't leave orphans accumulating between mint-time cleanups.
        """
        session, _ = self._session_with_cache(tmp_path, api_key="LIVE", cache_key=None)

        with patch("vip.auth._delete_api_key") as deleter:
            session.cleanup()

        deleter.assert_called_once_with(
            "https://c.example.com",
            "LIVE",
            "_vip_interactive_1",
            insecure=False,
            ca_bundle=None,
            proxy=None,
        )

    def test_deletes_when_cache_state_file_is_missing(self, tmp_path):
        """Meta without state is stale metadata — there is no cache the next
        run could actually load from, so our key is not reachable by
        future runs.  Delete it now so it doesn't orphan until the next
        mint sweeps stale keys.
        """
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
            "https://c.example.com",
            "LIVE",
            "_vip_interactive_1",
            insecure=False,
            ca_bundle=None,
            proxy=None,
        )

    def test_deletes_when_cache_state_file_is_malformed(self, tmp_path):
        """A corrupted cache state file is unusable — Playwright will fail to
        load it, so the next run won't actually reuse our key.  Treat the
        cache as unreachable and delete the key now rather than leaving
        an orphan until the next mint-time sweep.
        """
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
            "https://c.example.com",
            "LIVE",
            "_vip_interactive_1",
            insecure=False,
            ca_bundle=None,
            proxy=None,
        )

    def test_deletes_when_cache_references_a_different_key(self, tmp_path):
        """Concurrent run overwrote the cache with its own key → our key is
        no longer referenced and should be deleted so it doesn't linger.
        """
        session, _ = self._session_with_cache(tmp_path, api_key="MINE", cache_key="OTHER")

        with patch("vip.auth._delete_api_key") as deleter:
            session.cleanup()

        deleter.assert_called_once_with(
            "https://c.example.com",
            "MINE",
            "_vip_interactive_1",
            insecure=False,
            ca_bundle=None,
            proxy=None,
        )

    def test_deletes_when_session_has_no_cache_path(self, tmp_path):
        """Sessions created outside the caching flow (``_cache_path`` unset)
        behave like before: delete on cleanup.
        """
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
            "https://c.example.com",
            "LIVE",
            "_vip_interactive_1",
            insecure=False,
            ca_bundle=None,
            proxy=None,
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
        is a no-op so the loop iterates instantly.
        """

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
        and no longer contains ``/__login__``.
        """
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
        URL and is NOT a page whose URL contains sign-in/login/auth.
        """
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

    def test_timeout_raises_auth_timeout_error(self, monkeypatch):
        """If the URL never satisfies the completion condition before the
        deadline, the loop must raise AuthTimeoutError (a clean pytest
        exit via plugin.py's AuthConfigError handler, not INTERNALERROR --
        see #263) rather than continue or return silently.
        """
        from vip import auth as auth_mod

        stub = self._make_playwright_stub(["https://wb.example.com/auth-sign-in"])
        monkeypatch.setattr(auth_mod, "sync_playwright", lambda: stub)

        # First call computes the deadline, second is the loop's own
        # `while time.monotonic() < deadline` check — make it already
        # expired so the loop body never runs and page.url is never read.
        times = iter([0.0, 1000.0])
        monkeypatch.setattr(auth_mod.time, "monotonic", lambda: next(times))

        with pytest.raises(auth_mod.AuthTimeoutError, match="did not complete within 5 minutes"):
            auth_mod.start_interactive_auth(workbench_url="https://wb.example.com")

    def test_timeout_includes_final_url_and_expected_origin(self, monkeypatch):
        """The timeout error must report where the browser actually ended
        up and what origin was expected, so a diagnostic run can tell IdP
        stall apart from a bounce back to the product's own sign-in page
        (see #263).
        """
        from vip import auth as auth_mod

        stub = self._make_playwright_stub(["https://wb.example.com/auth-sign-in"])
        monkeypatch.setattr(auth_mod, "sync_playwright", lambda: stub)

        times = iter([0.0, 1000.0])
        monkeypatch.setattr(auth_mod.time, "monotonic", lambda: next(times))

        with pytest.raises(auth_mod.AuthTimeoutError) as exc_info:
            auth_mod.start_interactive_auth(workbench_url="https://wb.example.com")

        message = str(exc_info.value)
        assert "https://wb.example.com/auth-sign-in" in message
        assert "https://wb.example.com" in message

    def test_timeout_duration_reflects_vip_timeout_scale(self, monkeypatch):
        """VIP_TIMEOUT_SCALE=2 doubles the real wait to 10 minutes; the
        error text must say 10, not the constant's nominal 5 (see #263).
        """
        from vip import auth as auth_mod

        monkeypatch.setenv("VIP_TIMEOUT_SCALE", "2")
        stub = self._make_playwright_stub(["https://wb.example.com/auth-sign-in"])
        monkeypatch.setattr(auth_mod, "sync_playwright", lambda: stub)

        times = iter([0.0, 1000.0])
        monkeypatch.setattr(auth_mod.time, "monotonic", lambda: next(times))

        with pytest.raises(auth_mod.AuthTimeoutError, match="did not complete within 10 minutes"):
            auth_mod.start_interactive_auth(workbench_url="https://wb.example.com")


class TestStartInteractiveAuthSchemeResolutionWiring:
    """*_scheme_inferred flags gate calls to resolve_url_scheme (issue #537):
    an explicit scheme must never be second-guessed, and an inferred one
    must be resolved before Playwright or the mint client touch the URL.
    """

    @staticmethod
    def _playwright_stub(logged_in_url: str) -> MagicMock:
        """Stub sync_playwright() whose page is immediately "logged in" at
        *logged_in_url* (must match the resolved primary_url + no /__login__).
        """

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
        client -- not just one of the two.
        """
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
        assert resolve.call_args.kwargs == {"insecure": False, "ca_bundle": None, "proxy": None}
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
        behaviour: no probing.
        """
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


class TestAuthenticateWorkbench:
    """_authenticate_workbench establishes the Workbench SSO session after
    Connect auth has already succeeded.  Network failures here must NOT
    crash the pytest session — Connect tests should still run.  The
    helper returns ``None`` on success or a short failure reason that
    callers stash on :class:`InteractiveAuthSession` so test-time skip
    messages can quote the underlying cause.
    """

    def test_playwright_error_on_goto_is_non_fatal(self, capsys):
        """A PlaywrightError from page.goto() (e.g. ERR_CONNECTION_REFUSED,
        redirect-to-http) must be caught, logged as a warning, and return
        a failure reason.  Otherwise the whole pytest session dies with
        INTERNALERROR.  See issue #171.
        """
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
        bogus error on the session.
        """
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
        the workbench fixture can surface it instead of guessing.
        """
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

    def test_returns_reason_when_stuck_on_saml_acs_callback(self, monkeypatch):
        """Landing on Workbench's own SAML ACS endpoint must NOT be read as
        success. issue #263's diagnostic showed the quick check accepting
        it (it is on the Workbench origin and matches none of the old
        login keywords) the instant ``networkidle`` fired, before
        Workbench's own post-assertion redirect ran -- capturing a storage
        state with no valid session cookie, so the real login test later
        failed even though pre-test auth reported success.
        """
        from unittest.mock import PropertyMock

        from vip import auth as auth_mod

        page = MagicMock()
        page.goto.return_value = None
        page.wait_for_load_state.return_value = None
        type(page).url = PropertyMock(
            return_value="https://wb.example.com/saml/acs?SAMLResponse=abc123&RelayState=xyz"
        )

        times = iter([0.0, 1000.0])
        monkeypatch.setattr(auth_mod.time, "monotonic", lambda: next(times))

        result = auth_mod._authenticate_workbench(page, "https://wb.example.com")

        assert result is not None
        assert "did not complete" in result

    def test_timeout_reason_strips_oidc_query_parameters(self, monkeypatch):
        """The returned URL is surfaced in CI logs via the workbench skip
        message.  OIDC/SAML redirects can carry ``code=``, ``state=``,
        and ``SAMLRequest=`` query parameters — sensitive auth artifacts
        that must not leak.  Path is preserved so the failure is still
        debuggable.
        """
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

    def test_timeout_reason_includes_page_title(self, monkeypatch):
        """The returned reason must also surface the page title, so a
        stuck IdP confirmation page is distinguishable from a bounce back
        to Workbench's own sign-in page from the URL alone (see #263).
        """
        from unittest.mock import PropertyMock

        from vip import auth as auth_mod

        page = MagicMock()
        page.goto.return_value = None
        page.wait_for_load_state.return_value = None
        type(page).url = PropertyMock(return_value="https://wb.example.com/auth-sign-in")
        page.title.return_value = "Sign in to Workbench"

        times = iter([0.0, 1000.0])
        monkeypatch.setattr(auth_mod.time, "monotonic", lambda: next(times))

        result = auth_mod._authenticate_workbench(page, "https://wb.example.com")

        assert result is not None
        assert "Sign in to Workbench" in result

    def test_timeout_duration_reflects_vip_timeout_scale(self, monkeypatch):
        """VIP_TIMEOUT_SCALE=2 doubles the real wait; the reason must say
        so instead of the constant's nominal duration (see #263).
        """
        from unittest.mock import PropertyMock

        from vip import auth as auth_mod

        monkeypatch.setenv("VIP_TIMEOUT_SCALE", "2")
        page = MagicMock()
        page.goto.return_value = None
        page.wait_for_load_state.return_value = None
        type(page).url = PropertyMock(return_value="https://wb.example.com/auth-sign-in")

        times = iter([0.0, 1000.0])
        monkeypatch.setattr(auth_mod.time, "monotonic", lambda: next(times))

        result = auth_mod._authenticate_workbench(page, "https://wb.example.com")

        assert result is not None
        assert "did not complete within 10 minutes" in result

    def test_saml_provider_names_saml_in_message(self, monkeypatch):
        """Mirrors TestWaitForProductRedirectTimeout.test_saml_provider_names_saml_in_message:
        a SAML run's Workbench timeout reason must not hardcode OIDC (see #263).
        """
        from unittest.mock import PropertyMock

        from vip import auth as auth_mod

        page = MagicMock()
        page.goto.return_value = None
        page.wait_for_load_state.return_value = None
        type(page).url = PropertyMock(return_value="https://wb.example.com/auth-sign-in")

        times = iter([0.0, 1000.0])
        monkeypatch.setattr(auth_mod.time, "monotonic", lambda: next(times))

        result = auth_mod._authenticate_workbench(page, "https://wb.example.com", provider="saml")

        assert result is not None
        assert "SAML session may not be shared" in result
        assert "OIDC" not in result

    def test_unrecognized_provider_uses_neutral_wording(self, monkeypatch):
        """No provider (the default) must not assert a protocol the caller
        can't confirm — same convention as _wait_for_product_redirect.
        """
        from unittest.mock import PropertyMock

        from vip import auth as auth_mod

        page = MagicMock()
        page.goto.return_value = None
        page.wait_for_load_state.return_value = None
        type(page).url = PropertyMock(return_value="https://wb.example.com/auth-sign-in")

        times = iter([0.0, 1000.0])
        monkeypatch.setattr(auth_mod.time, "monotonic", lambda: next(times))

        result = auth_mod._authenticate_workbench(page, "https://wb.example.com")

        assert result is not None
        assert "The login session may not be shared" in result
        assert "OIDC" not in result
        assert "SAML" not in result


class TestWaitForProductRedirect:
    """_wait_for_product_redirect handles the Workbench OIDC confirmation page.

    After the IdP round-trip, Workbench shows a form with a "Sign in with
    OpenID" button that must be clicked to complete the session.  Headed
    flows rely on the user; headless flows must click it automatically.
    """

    @staticmethod
    def _page_with_urls(urls: list[str], *, oidc_button_visible: bool) -> MagicMock:
        """Stub a Page whose ``url`` returns each value in *urls* in order,
        repeating the last value once the list is exhausted.
        """
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
        button and stop polling once the URL settles on the dashboard.
        """
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
        try to click anything.
        """
        from vip.auth import _wait_for_product_redirect

        page = self._page_with_urls(
            ["https://wb.example.com/"],
            oidc_button_visible=False,
        )

        _wait_for_product_redirect(page, "https://wb.example.com")

        page.locator.return_value.first.click.assert_not_called()


class TestWaitForProductRedirectTimeout:
    """_wait_for_product_redirect's timeout error must name the actual
    protocol, state the real (scaled) duration, and report where the
    browser ended up.  Previously it hardcoded "OIDC" and "5 minutes" and
    said nothing about the final URL, so a SAML timeout was indistinguishable
    from a stuck IdP page or a bounce back to /auth-sign-in (see #263).
    """

    @staticmethod
    def _timed_out_page(monkeypatch, auth_mod, url: str, title: str = "Sign In") -> MagicMock:
        """A page stuck at *url* forever, with the deadline already expired
        so the poll loop's body never runs (no real wall-clock wait).
        """
        from unittest.mock import PropertyMock

        page = MagicMock()
        type(page).url = PropertyMock(return_value=url)
        page.title.return_value = title
        times = iter([0.0, 1000.0])
        monkeypatch.setattr(auth_mod.time, "monotonic", lambda: next(times))
        return page

    def test_saml_provider_names_saml_in_message(self, monkeypatch):
        from vip import auth as auth_mod

        page = self._timed_out_page(monkeypatch, auth_mod, "https://idp.example.com/saml/login")

        with pytest.raises(auth_mod.AuthTimeoutError, match="SAML login did not complete"):
            auth_mod._wait_for_product_redirect(page, "https://wb.example.com", provider="saml")

    def test_oidc_provider_names_oidc_in_message(self, monkeypatch):
        from vip import auth as auth_mod

        page = self._timed_out_page(monkeypatch, auth_mod, "https://idp.example.com/oidc/login")

        with pytest.raises(auth_mod.AuthTimeoutError, match="OIDC login did not complete"):
            auth_mod._wait_for_product_redirect(page, "https://wb.example.com", provider="oidc")

    def test_unrecognized_provider_uses_neutral_wording(self, monkeypatch):
        """No provider (or one that isn't oidc/saml/oauth2) must not
        assert a protocol the caller can't confirm.
        """
        from vip import auth as auth_mod

        page = self._timed_out_page(monkeypatch, auth_mod, "https://idp.example.com/login")

        with pytest.raises(auth_mod.AuthTimeoutError) as exc_info:
            auth_mod._wait_for_product_redirect(page, "https://wb.example.com")

        message = str(exc_info.value)
        assert message.startswith("Login did not complete")
        assert "OIDC" not in message
        assert "SAML" not in message

    def test_message_includes_final_url_title_and_expected_origin(self, monkeypatch):
        from vip import auth as auth_mod

        page = self._timed_out_page(
            monkeypatch,
            auth_mod,
            "https://idp.example.com/saml/login",
            title="Keycloak - Sign in to your account",
        )

        with pytest.raises(auth_mod.AuthTimeoutError) as exc_info:
            auth_mod._wait_for_product_redirect(page, "https://wb.example.com", provider="saml")

        message = str(exc_info.value)
        assert "https://idp.example.com/saml/login" in message
        assert "Keycloak - Sign in to your account" in message
        assert "https://wb.example.com" in message

    def test_duration_reflects_vip_timeout_scale(self, monkeypatch):
        """VIP_TIMEOUT_SCALE=2 doubles the real wait to 10 minutes; the
        error text must say 10, not the constant's nominal 5 (see #263).
        """
        from vip import auth as auth_mod

        monkeypatch.setenv("VIP_TIMEOUT_SCALE", "2")
        page = self._timed_out_page(monkeypatch, auth_mod, "https://idp.example.com/login")

        with pytest.raises(auth_mod.AuthTimeoutError, match="did not complete within 10 minutes"):
            auth_mod._wait_for_product_redirect(page, "https://wb.example.com", provider="oidc")

    def test_page_read_failure_does_not_mask_timeout(self, monkeypatch):
        """If the page is closed or crashed by the time the deadline fires,
        the diagnostic reads must not raise and swallow the real timeout.
        """
        from unittest.mock import PropertyMock

        from vip import auth as auth_mod

        page = MagicMock()
        type(page).url = PropertyMock(side_effect=RuntimeError("page closed"))
        page.title.side_effect = RuntimeError("page closed")
        times = iter([0.0, 1000.0])
        monkeypatch.setattr(auth_mod.time, "monotonic", lambda: next(times))

        with pytest.raises(auth_mod.AuthTimeoutError, match="did not complete"):
            auth_mod._wait_for_product_redirect(page, "https://wb.example.com", provider="oidc")


class TestAuthTimeoutErrorHierarchy:
    """AuthTimeoutError must subclass AuthConfigError -- that relationship
    is what lets plugin.py's existing ``except AuthConfigError`` handler
    convert a timeout into a clean ``pytest.UsageError`` instead of an
    INTERNALERROR traceback, with no change to that handler (see #263).
    """

    def test_is_subclass_of_auth_config_error(self):
        from vip.auth import AuthConfigError, AuthTimeoutError

        assert issubclass(AuthTimeoutError, AuthConfigError)

    def test_instance_is_caught_by_auth_config_error_except_clause(self):
        from vip.auth import AuthConfigError, AuthTimeoutError

        with pytest.raises(AuthConfigError) as excinfo:
            raise AuthTimeoutError("boom")
        assert isinstance(excinfo.value, AuthTimeoutError)


class TestClickWorkbenchOidcConfirm:
    """_click_workbench_oidc_confirm targets the specific Workbench form
    (``action='auth-openid-sign-in'``) so unrelated submit buttons on
    other login pages are not clicked by accident.
    """

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
        the surrounding wait loop.
        """
        from playwright.sync_api import Error as PlaywrightError

        from vip.auth import _click_workbench_oidc_confirm

        page = MagicMock()
        page.locator.side_effect = PlaywrightError("locator failed")

        assert _click_workbench_oidc_confirm(page) is False


class TestAuthenticatedPage:
    """Tests for authenticated_page(): the CLI cleanup escape hatch's
    browser-driven Workbench UI access (see vip.cli.run_cleanup).
    """

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

        with (
            patch("vip.auth.sync_playwright", return_value=pw),
            authenticated_page(session) as yielded_page,
        ):
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

        with (
            patch("vip.auth.sync_playwright", return_value=pw),
            authenticated_page(session, insecure=True),
        ):
            pass

        _, kwargs = browser.new_context.call_args
        assert kwargs["ignore_https_errors"] is True
        context.close.assert_called_once()

    def test_closes_browser_and_context_even_when_block_raises(self, tmp_path):
        session = self._make_session(tmp_path)

        pw = MagicMock()
        browser = pw.start.return_value.chromium.launch.return_value
        context = browser.new_context.return_value

        with (
            patch("vip.auth.sync_playwright", return_value=pw),
            pytest.raises(RuntimeError, match="boom"),
            authenticated_page(session),
        ):
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

        with (
            patch("vip.auth.sync_playwright", return_value=pw),
            authenticated_page(session, ca_bundle=ca_file),
        ):
            pass

        assert captured == [str(ca_file)]
        assert os.environ.get("NODE_EXTRA_CA_CERTS") is None
