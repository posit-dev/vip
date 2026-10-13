"""Selftests for ``join_session``, the shared "click the row's join link and
confirm the browser landed inside the session" helper. No real browser is
used: the page is a fake whose URL changes only when the join link is clicked.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from vip_tests.workbench import sessions
from vip_tests.workbench.conftest import join_session

_HOMEPAGE_URL = "http://localhost:8787/s/57ea13c286bd33c286bd3/workspaces/"
_SESSION_URL = "http://localhost:8787/s/92751cfc78a319a4c2e9b/?launcher=1"
_NAME = "VIP test_x.py - gw0-1"


class _FakePage:
    """A page that stays on the homepage until the join link has been clicked
    ``clicks_needed`` times, then moves to the session URL.
    """

    def __init__(self, *, clicks_needed: int | None, url: str = _HOMEPAGE_URL, tabs=()):
        self.url = url
        self.clicks = 0
        self.click_kwargs: list[dict] = []
        self._clicks_needed = clicks_needed
        self.reloads = 0
        self.context = MagicMock()
        self.context.pages = [self, *[MagicMock(url=u) for u in tabs]]
        self.selectors: list[str] = []

    def _click(self, **kwargs):
        self.clicks += 1
        self.click_kwargs.append(kwargs)
        if self._clicks_needed is not None and self.clicks >= self._clicks_needed:
            self.url = _SESSION_URL

    def locator(self, selector: str):
        self.selectors.append(selector)
        loc = MagicMock()
        loc.locator.side_effect = self.locator
        loc.click.side_effect = self._click
        loc.count.return_value = 0
        return loc

    def wait_for_url(self, predicate, timeout):
        if not predicate(self.url):
            raise PlaywrightTimeoutError(f"Timeout {timeout}ms exceeded.")

    def reload(self, **kwargs):
        self.reloads += 1

    def wait_for_timeout(self, ms):
        pass


@pytest.fixture(autouse=True)
def _row_is_active(monkeypatch):
    monkeypatch.setattr(
        sessions, "wait_for_session_active", lambda page, name, **kw: page.locator("row")
    )


def test_navigates_on_first_click_without_warning(caplog):
    page = _FakePage(clicks_needed=1)
    with caplog.at_level("WARNING"):
        join_session(page, _NAME)
    assert page.clicks == 1
    assert caplog.text == ""


def test_click_does_not_wait_for_navigation():
    """The click must not be what times out under CI load (#738)."""
    page = _FakePage(clicks_needed=1)
    join_session(page, _NAME)
    assert page.click_kwargs[0]["no_wait_after"] is True


def test_clicks_the_row_scoped_join_link():
    page = _FakePage(clicks_needed=1)
    join_session(page, _NAME)
    assert f"a[title='join {_NAME}']" in page.selectors


def test_retries_once_and_warns_visibly(caplog):
    page = _FakePage(clicks_needed=2)
    with caplog.at_level("WARNING"), pytest.warns(UserWarning, match="retrying"):
        join_session(page, _NAME)
    assert page.clicks == 2
    assert "retrying" in caplog.text
    assert _NAME in caplog.text


def test_fails_with_url_and_open_tabs_when_it_never_navigates():
    popup = "http://localhost:8787/s/aaaa/workspaces/"
    page = _FakePage(clicks_needed=None, tabs=(popup,))
    with pytest.warns(UserWarning, match="retrying"), pytest.raises(AssertionError) as err:
        join_session(page, _NAME)
    assert page.clicks == 2
    assert _HOMEPAGE_URL in str(err.value)
    assert popup in str(err.value)
    assert _NAME in str(err.value)


def test_does_not_click_when_already_inside_a_session():
    page = _FakePage(clicks_needed=1, url=_SESSION_URL)
    join_session(page, _NAME)
    assert page.clicks == 0


def test_reload_mode_reloads_until_active_then_joins(monkeypatch):
    page = _FakePage(clicks_needed=1)
    visible = iter([False, False, True])
    real_locator = page.locator

    def locator(selector):
        loc = real_locator(selector)
        if "Active" in selector:
            loc.count.return_value = 1
            loc.first.is_visible.side_effect = lambda: next(visible)
        return loc

    page.locator = locator
    join_session(page, _NAME, reload=True, reload_interval=0)
    assert page.reloads == 2
    assert page.clicks == 1


def test_reload_mode_returns_when_launch_navigated_into_the_session():
    """Some Workbench versions auto-navigate on Launch; do not wait for a badge
    that the session page will never show.
    """
    page = _FakePage(clicks_needed=1)

    def reload_into_session(**kwargs):
        page.url = _SESSION_URL

    page.reload = reload_into_session
    real_locator = page.locator

    def locator(selector):
        return real_locator(selector)

    page.locator = locator
    join_session(page, _NAME, reload=True, reload_interval=0)
    assert page.clicks == 0


def test_reload_mode_fails_if_session_never_becomes_active():
    page = _FakePage(clicks_needed=1)
    real_locator = page.locator

    def locator(selector):
        return real_locator(selector)

    page.locator = locator
    with pytest.raises(AssertionError, match="did not reach Active"):
        join_session(page, _NAME, reload=True, timeout=1, reload_interval=0)
    assert page.clicks == 0


def test_missing_join_link_fails_without_clicking():
    """A join link that never appears is reported as such, not as a navigation failure."""
    page = _FakePage(clicks_needed=1)
    original_locator = page.locator

    def locator(selector):
        loc = original_locator(selector)
        if "title='join" in selector:
            loc.wait_for.side_effect = PlaywrightTimeoutError("Timeout 10000ms exceeded.")
        return loc

    page.locator = locator
    with pytest.raises(AssertionError, match=r"join link .* never became visible"):
        join_session(page, _NAME)
    assert page.clicks == 0
