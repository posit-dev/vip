"""Selftests for WorkbenchClient VIP-session cleanup helpers.

No real network connections are made: the WorkbenchClient's internal
httpx client is replaced with one backed by httpx.MockTransport.
"""

from __future__ import annotations

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

    def get_attribute(self, name):
        if name == "aria-label":
            return f"select {self._page.session_names[self._index]}"
        return None

    def click(self, timeout=None):
        self._page._click(self._selector)


class _FakeHomepage:
    """Minimal Playwright Page double for the homepage session list.

    Models the rows the UI sweep interacts with: each row exposes a
    "select <name>" checkbox; clicking Quit removes the selected rows (unless
    *quit_removes* is False, simulating a quit that does not take effect, e.g.
    a confirm dialog that never appears). Confirm/force-quit dialog clicks
    raise (absent), exercising the helper's per-dialog try/except.
    """

    def __init__(self, session_names, *, quit_removes=True):
        self.session_names = list(session_names)
        self._quit_removes = quit_removes
        self._selected: list[str] = []
        self.clicked_checkbox_names: list[str] = []
        self.quit_clicks = 0
        self.reloads = 0

    def goto(self, *args, **kwargs):
        pass

    def reload(self, *args, **kwargs):
        self.reloads += 1

    def locator(self, selector):
        return _FakeLocator(self, selector)

    def _click(self, selector):
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
        # Confirm / force-quit dialogs: simulate "not present".
        raise RuntimeError(f"dialog not present: {selector}")


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
