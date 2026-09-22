"""Tests for vip.auth module — URL scheme resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest


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
        get probed and can fall back, driven by the real provenance value.
        """
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
        insecure wins — mirrors cli.py:391 logic.
        """
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
        upgraded.
        """
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
        prefix or a mock's success) is what gates the probe.
        """
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
        server genuinely doesn't answer -- triggers the http:// fallback.
        """
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
        transition, not a repeatable state a second call re-enters.
        """
        from vip.auth import resolve_url_scheme

        pc = self._pc("connect.example.com")

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")):
            resolve_url_scheme(pc)

        assert pc.url == "http://connect.example.com"
        assert pc.url_scheme_inferred is False

    def test_second_call_on_same_pc_is_a_pure_read_no_probe(self):
        """Once url_scheme_inferred is reset, a second call on the *same*
        ProductConfig must not touch the network at all -- not even a cache
        lookup is needed, since the flag itself now says "nothing to do".
        """
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
        still only probes once, via the module-level cache.
        """
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
        redirects, matching every other httpx call site in this module.
        """
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
        listener rather than this mock.
        """
        from vip.auth import resolve_url_scheme

        pc = self._pc("connect.example.com")

        with (
            patch("vip.auth._tls_listener_present", return_value=True),
            patch(
                "httpx.get",
                side_effect=httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]"),
            ),
        ):
            result = resolve_url_scheme(pc)

        assert result == "https://connect.example.com"
        assert pc.url == "https://connect.example.com"
        assert pc.url_scheme_inferred is False  # settled as https, not left ambiguous

    def test_tls_present_but_untrusted_names_the_remedy(self, capsys):
        """The warning for this case must be distinguishable from the
        "nothing answered" warning and must name the actual fix -- silently
        printing the same generic message as the network-unreachable case
        would leave a user with an untrusted cert no better off.
        """
        from vip.auth import resolve_url_scheme

        pc = self._pc("connect.example.com")

        with (
            patch("vip.auth._tls_listener_present", return_value=True),
            patch("httpx.get", side_effect=httpx.ConnectError("nope")),
        ):
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
        TLS configuration and might get a different, correct answer.
        """
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
        insecure/ca_bundle still cost only one probe.
        """
        from vip.auth import resolve_url_scheme

        pc1 = self._pc("connect.example.com")
        pc2 = self._pc("connect.example.com")

        with patch("httpx.get", side_effect=httpx.ConnectError("nope")) as mock_get:
            resolve_url_scheme(pc1, insecure=False)
            resolve_url_scheme(pc2, insecure=False)

        mock_get.assert_called_once()
