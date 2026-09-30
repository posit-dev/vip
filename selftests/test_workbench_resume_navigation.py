"""Selftests for ``_navigated_into_session``, which distinguishes a real
session URL from Workbench's own homepage URL (also served under
"/s/<id>/") -- something a bare "**/s/**" glob can't do. No real browser
is used: these test the pure URL classification.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from vip_tests.workbench.conftest import _navigated_into_session, wait_for_resume_navigation

_HOMEPAGE_URL = "http://localhost:8787/s/57ea13c286bd33c286bd3/workspaces/"
_SESSION_URL = "http://localhost:8787/s/92751cfc78a319a4c2e9b/?launcher=1"


def test_old_glob_check_could_not_tell_the_homepage_from_a_session():
    """Reproduces the bug: a bare "contains /s/" check -- what
    ``page.wait_for_url("**/s/**")`` reduces to -- passes on the homepage's
    own URL, so it can never catch a resume that silently stayed put.
    """
    assert "/s/" in _HOMEPAGE_URL
    assert "/s/" in _SESSION_URL


def test_homepage_url_is_not_a_session():
    assert _navigated_into_session(_HOMEPAGE_URL) is False


def test_session_url_is_a_session():
    assert _navigated_into_session(_SESSION_URL) is True


def test_bare_homepage_root_is_not_a_session():
    assert _navigated_into_session("http://localhost:8787/home") is False


def test_url_with_extra_path_after_workspaces_is_still_the_homepage():
    assert _navigated_into_session("http://localhost:8787/s/abc123/workspaces/") is False


def _page(url: str, other_urls: tuple[str, ...] = ()) -> MagicMock:
    page = MagicMock()
    page.url = url
    page.context.pages = [page, *[MagicMock(url=u) for u in other_urls]]
    return page


def test_wait_for_resume_navigation_true_when_url_reaches_a_session():
    page = _page(_SESSION_URL)
    assert wait_for_resume_navigation(page, timeout=1) is True
    page.wait_for_url.assert_called_once_with(_navigated_into_session, timeout=1)


def test_wait_for_resume_navigation_false_when_browser_stays_on_the_homepage():
    """Nightly runs 34673463899..36669984616: Launch leaves the page on the
    homepage, so the wait must report that instead of raising.
    """
    page = _page(_HOMEPAGE_URL)
    page.wait_for_url.side_effect = PlaywrightTimeoutError("Timeout 15000ms exceeded.")
    assert wait_for_resume_navigation(page, timeout=1) is False


def test_wait_for_resume_navigation_reports_url_and_open_tabs_on_timeout(caplog):
    popup = "http://localhost:8787/s/92751cfc78a319a4c2e9b/"
    page = _page(_HOMEPAGE_URL, other_urls=(popup,))
    page.wait_for_url.side_effect = PlaywrightTimeoutError("Timeout 15000ms exceeded.")
    with caplog.at_level("WARNING"):
        wait_for_resume_navigation(page, timeout=1)
    assert _HOMEPAGE_URL in caplog.text
    assert popup in caplog.text
