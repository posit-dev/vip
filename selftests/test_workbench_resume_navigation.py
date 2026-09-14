"""Selftests for detecting real navigation into a resumed session.

Two live CI runs of the suspend/resume scenario (rstudio/rstudio-pro's
"Workbench VIP Tests", 2026-09-11 and 2026-09-14) timed out waiting for
RStudio content after resuming a session, even though the diagnostics
collector showed the backend completed the resume in under 2 seconds both
times. The browser's own aria snapshot at timeout showed it was still on the
homepage's Projects table, not inside the session.

The cause: the step's navigation check was ``page.wait_for_url("**/s/**")``,
meant to confirm the browser had left the homepage for the resumed session's
URL. But Workbench's homepage is itself served under a "/s/<id>/" URL (both
failures landed on "/s/57ea13c286bd33c286bd3/workspaces/"), so that glob is
satisfied by the homepage's own URL and never proves navigation happened.

No real browser is used: these test the pure URL classification.
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
