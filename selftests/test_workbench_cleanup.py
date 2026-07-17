"""Selftests for WorkbenchClient VIP-session cleanup helpers.

No real network connections are made: the WorkbenchClient's internal
httpx client is replaced with one backed by httpx.MockTransport.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from vip.clients.workbench import WorkbenchClient, is_vip_session


@pytest.mark.parametrize(
    "label, expected",
    [
        ("VIP test_ide_launch.py - gw0-123", True),
        ("VIP foo", True),
        ("_vip_cap_1700000000_default_0", True),
        ("My analysis", False),
        ("vip lowercase no space", False),
        ("", False),
    ],
)
def test_is_vip_session(label, expected):
    assert is_vip_session(label) is expected


def _client_with_handler(handler) -> WorkbenchClient:
    """Build a WorkbenchClient whose httpx client uses a MockTransport."""
    wc = WorkbenchClient("https://wb.example.com")
    wc._client.close()
    wc._client = httpx.Client(
        base_url="https://wb.example.com",
        transport=httpx.MockTransport(handler),
    )
    return wc


def test_quit_vip_sessions_targets_only_vip_and_skips_others():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/sessions":
            return httpx.Response(
                200,
                json=[
                    {"id": "a", "label": "VIP foo"},
                    {"id": "b", "label": "My real work"},
                    {"id": "c", "label": "_vip_cap_1_default_0"},
                ],
            )
        return httpx.Response(200)

    wc = _client_with_handler(handler)
    quit_count = wc.quit_vip_sessions(retries=1)

    assert quit_count == 2
    assert ("DELETE", "/api/sessions/a") in calls
    assert ("DELETE", "/api/sessions/c") in calls
    assert ("DELETE", "/api/sessions/b") not in calls


def test_quit_vip_sessions_retries_until_gone():
    list_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/sessions":
            list_calls["n"] += 1
            # First list shows the session; second list shows it gone.
            if list_calls["n"] == 1:
                return httpx.Response(200, json=[{"id": "a", "label": "VIP foo"}])
            return httpx.Response(200, json=[])
        return httpx.Response(200)

    wc = _client_with_handler(handler)
    quit_count = wc.quit_vip_sessions(retries=3, settle_seconds=0)

    assert quit_count == 1
    assert list_calls["n"] == 2  # stopped re-listing once the session was gone


def test_quit_vip_sessions_falls_back_to_suspend():
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/sessions":
            return httpx.Response(200, json=[{"id": "a", "label": "VIP foo"}])
        if request.method == "DELETE":
            return httpx.Response(405)
        return httpx.Response(200)  # suspend succeeds

    wc = _client_with_handler(handler)
    quit_count = wc.quit_vip_sessions(retries=1)

    assert quit_count == 1
    assert ("DELETE", "/api/sessions/a") in calls
    assert ("POST", "/api/sessions/a/suspend") in calls


def test_quit_vip_sessions_returns_zero_on_non_200_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    wc = _client_with_handler(handler)
    assert wc.quit_vip_sessions(retries=2, settle_seconds=0) == 0


def test_quit_vip_sessions_does_not_raise_on_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    wc = _client_with_handler(handler)
    assert wc.quit_vip_sessions(retries=2, settle_seconds=0) == 0


def test_quit_vip_sessions_does_not_raise_on_invalid_json():
    """A 200 response whose body is not JSON must not raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    wc = _client_with_handler(handler)
    assert wc.quit_vip_sessions(retries=2, settle_seconds=0) == 0


def test_quit_vip_sessions_handles_non_list_body():
    """A 200 response whose JSON is not a list must not raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"oops": True})

    wc = _client_with_handler(handler)
    assert wc.quit_vip_sessions(retries=2, settle_seconds=0) == 0


def test_quit_vip_sessions_skips_null_label_and_non_dict_items():
    """Null labels and non-dict list items are skipped without raising."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/sessions":
            return httpx.Response(
                200,
                json=[
                    {"id": "a", "label": None},
                    "garbage",
                    42,
                    {"id": "b", "label": "VIP ok"},
                ],
            )
        return httpx.Response(200)

    wc = _client_with_handler(handler)
    # Only the valid VIP session is acted on; bad entries are ignored.
    assert wc.quit_vip_sessions(retries=1) == 1


def test_quit_vip_sessions_counts_unique_sessions_under_retry():
    """A session that persists across retries is counted once, not per attempt."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/sessions":
            # Always still listed → forces a fresh quit attempt each round.
            return httpx.Response(200, json=[{"id": "a", "label": "VIP stuck"}])
        return httpx.Response(200)  # DELETE "succeeds" but the session persists

    wc = _client_with_handler(handler)
    # 3 attempts each DELETE "a" successfully, but it is one unique session.
    assert wc.quit_vip_sessions(retries=3, settle_seconds=0) == 1


def test_quit_vip_sessions_warns_when_stuck_session_persists(caplog):
    """A VIP session that never disappears across all retries must WARN (issue #467).

    quit_session() treats any HTTP status < 400 as success without verifying
    termination -- so a deployment whose DELETE is a silent no-op looks
    "successful" while the session persists. The final re-check after the
    retry loop must catch that and log loudly instead of returning quietly.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/sessions":
            # Always still listed -- simulates a no-op DELETE/suspend.
            return httpx.Response(200, json=[{"id": "a", "label": "VIP stuck"}])
        return httpx.Response(200)

    wc = _client_with_handler(handler)
    with caplog.at_level(logging.WARNING):
        quit_count = wc.quit_vip_sessions(retries=2, settle_seconds=0)

    assert quit_count == 1  # the quit call "succeeded" once, distinct session
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "expected a WARNING when a VIP session persists after cleanup"
    assert any("VIP stuck" in r.message for r in warnings)
    assert any("id=a" in r.message for r in warnings)


def test_quit_vip_sessions_no_warning_when_fully_cleaned(caplog):
    """No warning should fire when the retry loop confirms everything is gone."""
    list_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/sessions":
            list_calls["n"] += 1
            if list_calls["n"] == 1:
                return httpx.Response(200, json=[{"id": "a", "label": "VIP foo"}])
            return httpx.Response(200, json=[])
        return httpx.Response(200)

    wc = _client_with_handler(handler)
    with caplog.at_level(logging.WARNING):
        quit_count = wc.quit_vip_sessions(retries=3, settle_seconds=0)

    assert quit_count == 1
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_count_vip_sessions_counts_only_vip():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"id": "a", "label": "VIP foo"},
                {"id": "b", "label": "My real work"},
                {"id": "c", "label": "_vip_cap_1_default_0"},
            ],
        )

    wc = _client_with_handler(handler)
    assert wc.count_vip_sessions() == 2


def test_count_vip_sessions_zero_when_no_vip_sessions():
    wc = _client_with_handler(lambda r: httpx.Response(200, json=[{"id": "b", "label": "real"}]))
    assert wc.count_vip_sessions() == 0


def test_count_vip_sessions_minus_one_on_non_200():
    wc = _client_with_handler(lambda r: httpx.Response(503))
    assert wc.count_vip_sessions() == -1


def test_count_vip_sessions_minus_one_on_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    wc = _client_with_handler(handler)
    assert wc.count_vip_sessions() == -1


def test_count_vip_sessions_minus_one_on_non_list_json():
    # A 200 whose body is a JSON object (not the expected array) must read as
    # "unknown" (-1), never as "confirmed clean" (0) — else the caller would
    # suppress the UI escalation and re-orphan sessions (issue #467).
    wc = _client_with_handler(lambda r: httpx.Response(200, json={"error": "nope"}))
    assert wc.count_vip_sessions() == -1


def test_count_vip_sessions_minus_one_on_non_json_body():
    wc = _client_with_handler(lambda r: httpx.Response(200, text="<html>app</html>"))
    assert wc.count_vip_sessions() == -1


def test_sessions_api_reachable_true_on_200():
    wc = _client_with_handler(lambda r: httpx.Response(200, json=[]))
    assert wc.sessions_api_reachable() is True


def test_sessions_api_reachable_false_on_404():
    wc = _client_with_handler(lambda r: httpx.Response(404, text="<html>not found</html>"))
    assert wc.sessions_api_reachable() is False


def test_sessions_api_reachable_false_on_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    wc = _client_with_handler(handler)
    assert wc.sessions_api_reachable() is False


def test_sessions_api_reachable_false_on_redirect_to_login():
    # 302 is < 400 but is not a usable session list (e.g. auth bounce).
    wc = _client_with_handler(lambda r: httpx.Response(302, headers={"location": "/auth-sign-in"}))
    assert wc.sessions_api_reachable() is False


def test_sessions_api_reachable_false_on_200_html():
    # Some deployments serve the SPA (200 HTML) for unknown API paths.
    wc = _client_with_handler(lambda r: httpx.Response(200, text="<html>app</html>"))
    assert wc.sessions_api_reachable() is False


def test_sessions_api_reachable_false_on_200_non_list_json():
    # 200 with a JSON object (not the expected session array) is not usable.
    wc = _client_with_handler(lambda r: httpx.Response(200, json={"error": "nope"}))
    assert wc.sessions_api_reachable() is False


def test_vip_names_from_select_labels_keeps_only_vip():
    from vip_tests.workbench.conftest import _vip_names_from_select_labels

    labels = [
        "select VIP test_jobs.py - gw0-1",
        "select My real work",
        "select _vip_cap_1_default_0",
        "garbage without prefix",
        "VIP no select prefix",
    ]
    assert _vip_names_from_select_labels(labels) == [
        "VIP test_jobs.py - gw0-1",
        "_vip_cap_1_default_0",
    ]


def test_quit_vip_sessions_via_ui_never_raises_on_failure():
    """A navigation/Playwright failure must not propagate out of cleanup."""
    from vip_tests.workbench.conftest import _quit_vip_sessions_via_ui

    class _BoomPage:
        def goto(self, *args, **kwargs):
            raise RuntimeError("navigation failed")

    assert _quit_vip_sessions_via_ui(_BoomPage(), "https://wb.example.com") == 0


def test_session_api_reachable_via_cookies_delegates_and_never_raises(monkeypatch):
    from vip_tests.workbench import conftest as wb

    monkeypatch.setattr(wb.WorkbenchClient, "sessions_api_reachable", lambda self: True)
    assert (
        wb._session_api_reachable_via_cookies(
            "https://wb.example.com", {"c": "v"}, insecure=False, ca_bundle=None
        )
        is True
    )

    def boom(self):
        raise RuntimeError("nope")

    monkeypatch.setattr(wb.WorkbenchClient, "sessions_api_reachable", boom)
    assert (
        wb._session_api_reachable_via_cookies(
            "https://wb.example.com", {}, insecure=False, ca_bundle=None
        )
        is False
    )


class _FakeLocator:
    """Stand-in for a Playwright Locator over the homepage session list."""

    def __init__(self, page, selector, index=0):
        self._page = page
        self._selector = selector
        self._index = index

    def count(self) -> int:
        return len(self._page.session_names)

    def nth(self, i):
        return _FakeLocator(self._page, self._selector, i)

    @property
    def first(self):
        return self

    def is_visible(self):
        # The fake models an already-authenticated homepage, so the Posit logo
        # (the "logged in" marker _complete_sso_if_needed checks) is visible;
        # nothing else is.
        from vip_tests.workbench.pages import Homepage

        return self._selector == Homepage.POSIT_LOGO

    def get_attribute(self, name):
        if name == "aria-label":
            return f"select {self._page.session_names[self._index]}"
        return None

    def wait_for(self, *, state=None, timeout=None):
        from vip_tests.workbench.pages import Homepage

        # The Posit logo is the authenticated-homepage marker (see is_visible);
        # _complete_sso_if_needed now wait_for()s it rather than snapshotting,
        # so model it as present. Other selectors "appear" only when registered
        # as a present dialog; otherwise they time out.
        if self._selector == Homepage.POSIT_LOGO:
            return
        if self._selector not in self._page.present_dialogs:
            raise RuntimeError(f"locator not visible: {self._selector}")

    def click(self, timeout=None):
        self._page._click(self._selector, timeout)


class _FakeHomepage:
    """Minimal Playwright Page double for the homepage session list.

    Models the rows the UI sweep interacts with: each row exposes a
    "select <name>" checkbox; clicking Quit removes the selected rows (unless
    *quit_removes* is False, simulating a quit that does not take effect, e.g.
    a confirm dialog that never appears). Only selectors in *present_dialogs*
    are "visible" to wait_for; any others time out (absent), exercising the
    helper's per-dialog skip path. Dialog clicks are recorded as
    (selector, timeout) so tests can assert which timeout was used.
    """

    def __init__(self, session_names, *, quit_removes=True, present_dialogs=()):
        self.session_names = list(session_names)
        self._quit_removes = quit_removes
        self.present_dialogs = set(present_dialogs)
        self._selected: list[str] = []
        self.clicked_checkbox_names: list[str] = []
        self.dialog_clicks: list[tuple[str, object]] = []
        self.quit_clicks = 0
        self.reloads = 0
        self.goto_urls: list[str] = []
        # Authenticated homepage URL (Workbench redirects the root into an
        # active session's workspace); not a login page, so _complete_sso_if_needed
        # takes the bounded-logo-wait path.
        self.url = "https://wb.example.com/s/abc123/workspaces/"

    def goto(self, url, *args, **kwargs):
        self.goto_urls.append(url)
        self.url = url

    def reload(self, *args, **kwargs):
        self.reloads += 1

    def locator(self, selector):
        return _FakeLocator(self, selector)

    def _click(self, selector, timeout=None):
        from vip_tests.workbench.pages import Homepage

        prefix = "[aria-label='select "
        if selector.startswith(prefix):
            name = selector[len(prefix) : -2]  # strip prefix and trailing "']"
            self.clicked_checkbox_names.append(name)
            if name in self.session_names:
                self._selected.append(name)
            return
        if selector == Homepage.QUIT_BUTTON:
            self.quit_clicks += 1
            if self._quit_removes:
                for name in self._selected:
                    if name in self.session_names:
                        self.session_names.remove(name)
            self._selected = []
            return
        # A confirm/force-quit dialog click — only reached when wait_for found
        # it present. Record the selector and the timeout used.
        self.dialog_clicks.append((selector, timeout))


def test_quit_vip_sessions_via_ui_quits_only_vip_rows_and_counts_distinct():
    from vip_tests.workbench.conftest import _quit_vip_sessions_via_ui

    page = _FakeHomepage(
        ["VIP test_jobs.py - gw0-1", "My real work", "_vip_cap_1_default_0"],
        quit_removes=True,
    )
    count = _quit_vip_sessions_via_ui(page, "https://wb.example.com")

    assert count == 2
    assert "My real work" not in page.clicked_checkbox_names
    assert set(page.clicked_checkbox_names) == {
        "VIP test_jobs.py - gw0-1",
        "_vip_cap_1_default_0",
    }
    assert page.session_names == ["My real work"]


def test_quit_vip_sessions_via_ui_counts_persisting_session_once():
    from vip_tests.workbench.conftest import _quit_vip_sessions_via_ui

    # Quit "succeeds" but the row never disappears, so the same VIP session is
    # re-selected every iteration. The count must reflect distinct sessions.
    page = _FakeHomepage(["VIP stuck - gw0-9"], quit_removes=False)
    count = _quit_vip_sessions_via_ui(page, "https://wb.example.com", max_iterations=4)

    assert count == 1
    assert page.quit_clicks == 4


def test_quit_vip_sessions_via_ui_clicks_present_dialog_with_normal_timeout():
    from vip_tests.workbench.conftest import TIMEOUT_QUICK, _quit_vip_sessions_via_ui
    from vip_tests.workbench.pages import Homepage

    page = _FakeHomepage(
        ["VIP one - gw0-1"],
        quit_removes=True,
        present_dialogs={Homepage.CONFIRM_QUIT},
    )
    count = _quit_vip_sessions_via_ui(page, "https://wb.example.com")

    assert count == 1
    # The present confirm dialog is clicked, and with the normal timeout (not the
    # short probe) so a slow-but-present dialog still completes. Absent dialogs
    # (force-quit follow-ups) are not clicked.
    assert page.dialog_clicks == [(Homepage.CONFIRM_QUIT, TIMEOUT_QUICK)]


def test_quit_vip_sessions_via_ui_navigates_to_root_not_home():
    """The sweep must load the homepage at the site root, not ``/home``.

    On WB 2026.06 the session table lives at the root (the URL the tests use);
    ``/home`` renders no session list, which silently orphaned sessions (#467).
    """
    from vip_tests.workbench.conftest import _quit_vip_sessions_via_ui

    page = _FakeHomepage(["VIP one - gw0-1"], quit_removes=True)
    _quit_vip_sessions_via_ui(page, "https://wb.example.com/")

    assert page.goto_urls[0] == "https://wb.example.com"
    assert not any(u.endswith("/home") for u in page.goto_urls)


def test_quit_vip_sessions_via_ui_bails_when_sso_cannot_complete(monkeypatch):
    """When the homepage can't be reached (SSO not completed), quit 0 and warn."""
    import vip.workbench_ui as wbui

    monkeypatch.setattr(wbui, "_complete_sso_if_needed", lambda page: False)
    page = _FakeHomepage(["VIP one - gw0-1"], quit_removes=True)
    assert wbui.quit_vip_sessions_via_ui(page, "https://wb.example.com") == 0
    # It never tried to enumerate/quit rows once auth failed.
    assert page.quit_clicks == 0


class _SsoFakePage:
    """Page double for :func:`_complete_sso_if_needed`.

    Models an OIDC sign-in page: a "Sign in with OpenID" button whose click
    completes a silent SSO (making the homepage logo appear) iff *idp_valid*.
    """

    def __init__(
        self, *, url, logo_visible=False, sso_visible=True, has_username=False, idp_valid=True
    ):
        self.url = url
        self._logo_visible = logo_visible
        self._sso_visible = sso_visible
        self._has_username = has_username
        self._idp_valid = idp_valid
        self.sso_clicked = False

    def locator(self, selector):
        from vip_tests.workbench.pages import Homepage, LoginPage

        if selector == Homepage.POSIT_LOGO:
            return _SsoFakeLocator(lambda: self._logo_visible)
        if selector == LoginPage.USERNAME:
            return _SsoFakeLocator(lambda: self._has_username)
        return _SsoFakeLocator(lambda: False)

    def get_by_role(self, role, name=None):
        page = self

        def _on_click() -> None:
            page.sso_clicked = True
            if page._idp_valid:
                page._logo_visible = True

        return _SsoFakeLocator(lambda: page._sso_visible, on_click=_on_click)


class _SsoFakeLocator:
    def __init__(self, is_visible_fn, *, on_click=None):
        self._is_visible_fn = is_visible_fn
        self._on_click = on_click

    @property
    def first(self):
        return self

    def is_visible(self):
        return self._is_visible_fn()

    def wait_for(self, *, state=None, timeout=None):
        if not self._is_visible_fn():
            raise RuntimeError("not visible")

    def click(self, timeout=None):
        if self._on_click is not None:
            self._on_click()


def test_complete_sso_true_when_already_authenticated():
    from vip.workbench_ui import _complete_sso_if_needed

    page = _SsoFakePage(url="https://wb.example.com/", logo_visible=True)
    assert _complete_sso_if_needed(page) is True
    assert page.sso_clicked is False  # no SSO needed


def test_complete_sso_clicks_button_and_succeeds_with_valid_idp():
    from vip.workbench_ui import _complete_sso_if_needed

    page = _SsoFakePage(url="https://wb.example.com/auth-sign-in?appUri=%2F", idp_valid=True)
    assert _complete_sso_if_needed(page) is True
    assert page.sso_clicked is True


def test_complete_sso_false_when_idp_session_expired():
    from vip.workbench_ui import _complete_sso_if_needed

    # SSO button present and clicked, but the homepage logo never appears.
    page = _SsoFakePage(url="https://wb.example.com/auth-sign-in", idp_valid=False)
    assert _complete_sso_if_needed(page) is False
    assert page.sso_clicked is True


def test_complete_sso_false_on_password_form():
    from vip.workbench_ui import _complete_sso_if_needed

    # A username field means a password form, not silent SSO: don't click.
    page = _SsoFakePage(url="https://wb.example.com/auth-sign-in", has_username=True)
    assert _complete_sso_if_needed(page) is False
    assert page.sso_clicked is False


def test_complete_sso_false_when_not_on_login_page():
    from vip.workbench_ui import _complete_sso_if_needed

    # No logo and not a login URL — nothing we can do.
    page = _SsoFakePage(url="https://wb.example.com/some/other/page", sso_visible=False)
    assert _complete_sso_if_needed(page) is False


class _DelayedLogoLocator:
    """Logo a one-shot is_visible() snapshot misses but a bounded wait_for()
    catches -- models the shadcn SPA mounting the logo a few seconds after the
    page ``load`` event (issue #491)."""

    def __init__(self):
        self.waited = False

    @property
    def first(self):
        return self

    def is_visible(self):
        return False  # snapshot loses the hydration race

    def wait_for(self, *, state=None, timeout=None):
        self.waited = True  # bounded wait catches the logo once it mounts

    def click(self, timeout=None):
        pass


class _HydrationRacePage:
    """Authenticated homepage whose logo mounts after ``load``; Workbench has
    redirected the root URL into an active session's workspace (issue #491)."""

    def __init__(self, url="https://wb.example.com/s/abc123/workspaces/"):
        self.url = url
        self.logo = _DelayedLogoLocator()

    def locator(self, selector):
        from vip_tests.workbench.pages import Homepage

        if selector == Homepage.POSIT_LOGO:
            return self.logo
        return _SsoFakeLocator(lambda: False)

    def get_by_role(self, role, name=None):
        return _SsoFakeLocator(lambda: False)  # no SSO button should be reached


def test_complete_sso_true_when_logo_mounts_after_load():
    """Regression for #491: the authenticated homepage's logo mounts a few
    seconds after ``load`` (shadcn hydration), and Workbench redirects the root
    URL into an active session's workspace. A one-shot ``is_visible()`` snapshot
    raced hydration and returned False, aborting the cleanup sweep with a
    misleading expired-session warning even though the session list was
    reachable. A bounded ``wait_for`` must detect the logo and report
    authenticated."""
    from vip.workbench_ui import _complete_sso_if_needed

    page = _HydrationRacePage()
    assert _complete_sso_if_needed(page) is True
    assert page.logo.waited is True  # used the bounded wait, not a snapshot


# ---------------------------------------------------------------------------
# _run_session_cleanup — escalation logic (issue #467)
# ---------------------------------------------------------------------------


def _fake_vip_config(*, api_key: str = ""):
    from types import SimpleNamespace

    workbench = SimpleNamespace(api_key=api_key)
    return SimpleNamespace(workbench=workbench, insecure=False, ca_bundle=None)


def _fake_page(cookies: list[dict]):
    from types import SimpleNamespace

    return SimpleNamespace(context=SimpleNamespace(cookies=lambda: cookies))


def _fresh_state() -> dict[str, object]:
    return {"cookies": None, "base_url": None, "api_reachable": None}


def _recording_ui_sweep(ui_calls: list[tuple], return_value: int = 0):
    """Build a fake ``_quit_vip_sessions_via_ui`` that records its (page, base_url) call."""

    def _fake(page, base_url, **_k):
        ui_calls.append((page, base_url))
        return return_value

    return _fake


def test_run_session_cleanup_escalates_to_ui_when_api_leaves_leftovers(monkeypatch):
    """API sweep runs but VIP sessions remain -> the UI sweep must fire.

    This is the core #467 fix: a reachable API whose DELETE is a no-op must
    not be trusted just because it didn't error.
    """
    from types import SimpleNamespace

    from vip_tests.workbench import conftest as wb

    ui_calls: list[tuple] = []

    monkeypatch.setattr(wb, "_quit_vip_sessions_via_cookies", lambda *a, **k: 1)
    monkeypatch.setattr(wb, "_session_api_reachable_via_cookies", lambda *a, **k: True)
    monkeypatch.setattr(wb, "_vip_session_count_via_cookies", lambda *a, **k: 1)
    monkeypatch.setattr(wb, "_quit_vip_sessions_via_ui", _recording_ui_sweep(ui_calls, 1))

    page = _fake_page([{"name": "a", "value": "b"}])
    workbench_client = SimpleNamespace(base_url="https://wb.example.com")
    state = _fresh_state()

    wb._run_session_cleanup(page, workbench_client, _fake_vip_config(), state)

    assert len(ui_calls) == 1
    assert ui_calls[0][1] == "https://wb.example.com"


def test_run_session_cleanup_skips_ui_when_api_sweep_fully_cleans(monkeypatch):
    """API reachable and confirmed zero VIP sessions remaining -> no UI escalation."""
    from types import SimpleNamespace

    from vip_tests.workbench import conftest as wb

    ui_calls: list[tuple] = []

    monkeypatch.setattr(wb, "_quit_vip_sessions_via_cookies", lambda *a, **k: 1)
    monkeypatch.setattr(wb, "_session_api_reachable_via_cookies", lambda *a, **k: True)
    monkeypatch.setattr(wb, "_vip_session_count_via_cookies", lambda *a, **k: 0)
    monkeypatch.setattr(wb, "_quit_vip_sessions_via_ui", _recording_ui_sweep(ui_calls, 0))

    page = _fake_page([{"name": "a", "value": "b"}])
    workbench_client = SimpleNamespace(base_url="https://wb.example.com")
    state = _fresh_state()

    wb._run_session_cleanup(page, workbench_client, _fake_vip_config(), state)

    assert ui_calls == []


def test_run_session_cleanup_escalates_when_api_unreachable(monkeypatch):
    """Existing behavior preserved: an unreachable API still escalates to the UI."""
    from types import SimpleNamespace

    from vip_tests.workbench import conftest as wb

    ui_calls: list[tuple] = []

    monkeypatch.setattr(wb, "_quit_vip_sessions_via_cookies", lambda *a, **k: 0)
    monkeypatch.setattr(wb, "_session_api_reachable_via_cookies", lambda *a, **k: False)
    monkeypatch.setattr(wb, "_vip_session_count_via_cookies", lambda *a, **k: -1)
    monkeypatch.setattr(wb, "_quit_vip_sessions_via_ui", _recording_ui_sweep(ui_calls, 0))

    page = _fake_page([{"name": "a", "value": "b"}])
    workbench_client = SimpleNamespace(base_url="https://wb.example.com")
    state = _fresh_state()

    wb._run_session_cleanup(page, workbench_client, _fake_vip_config(), state)

    assert len(ui_calls) == 1


def test_run_session_cleanup_warns_when_no_cookies_and_no_api_key(monkeypatch, caplog):
    """No browser cookies and no [workbench] api_key -> warn, do not attempt any sweep."""
    from types import SimpleNamespace

    from vip_tests.workbench import conftest as wb

    def _fail(*a, **k):
        pytest.fail("no sweep should be attempted without cookies or an api_key")

    monkeypatch.setattr(wb, "_quit_vip_sessions_via_cookies", _fail)
    monkeypatch.setattr(wb, "_session_api_reachable_via_cookies", _fail)
    monkeypatch.setattr(wb, "_vip_session_count_via_cookies", _fail)
    monkeypatch.setattr(wb, "_quit_vip_sessions_via_ui", _fail)

    page = _fake_page([])
    workbench_client = SimpleNamespace(base_url="https://wb.example.com")
    state = _fresh_state()

    with caplog.at_level(logging.WARNING):
        wb._run_session_cleanup(page, workbench_client, _fake_vip_config(api_key=""), state)

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "expected a warning when cleanup cannot authenticate"
    assert any("authenticate" in r.message for r in warnings)


def test_run_session_cleanup_no_warning_when_no_cookies_but_api_key_present(monkeypatch, caplog):
    """No browser cookies but an api_key is configured -> no warning (belt-and-suspenders
    end-of-run sweep will use the api_key), and no per-test sweep is attempted either
    (cookies are required for the per-test cookie-authenticated sweep)."""
    from types import SimpleNamespace

    from vip_tests.workbench import conftest as wb

    def _fail(*a, **k):
        pytest.fail("no cookie-based sweep should run without cookies")

    monkeypatch.setattr(wb, "_quit_vip_sessions_via_cookies", _fail)
    monkeypatch.setattr(wb, "_session_api_reachable_via_cookies", _fail)
    monkeypatch.setattr(wb, "_vip_session_count_via_cookies", _fail)
    monkeypatch.setattr(wb, "_quit_vip_sessions_via_ui", _fail)

    page = _fake_page([])
    workbench_client = SimpleNamespace(base_url="https://wb.example.com")
    state = _fresh_state()

    with caplog.at_level(logging.WARNING):
        wb._run_session_cleanup(page, workbench_client, _fake_vip_config(api_key="k"), state)

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_run_session_cleanup_returns_early_when_workbench_client_is_none(monkeypatch):
    """workbench_client=None (product not configured) -> no-op, no errors."""
    from vip_tests.workbench import conftest as wb

    page = _fake_page([{"name": "a", "value": "b"}])
    state = _fresh_state()

    wb._run_session_cleanup(page, None, _fake_vip_config(), state)  # must not raise
