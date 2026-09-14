"""Selftests for ``_navigated_into_session``, which distinguishes a real
session URL from Workbench's own homepage URL (also served under
"/s/<id>/") -- something a bare "**/s/**" glob can't do. No real browser
is used: these test the pure URL classification.
"""

from __future__ import annotations

from vip_tests.workbench.conftest import _navigated_into_session

_HOMEPAGE_URL = "http://localhost:8787/s/57ea13c286bd33c286bd3/workspaces/"
_SESSION_URL = "http://localhost:8787/s/92751cfc78a319a4c2e9b/?launcher=1"


def test_old_glob_check_could_not_tell_the_homepage_from_a_session():
    """Reproduces the bug: a bare "contains /s/" check -- what
    ``page.wait_for_url("**/s/**")`` reduces to -- passes on the homepage's
    own URL, so it can never catch a resume that silently stayed put."""
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
