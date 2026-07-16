"""Browser-driven Workbench session-cleanup helpers.

This module lives under ``src/vip/`` (rather than ``src/vip_tests/``,
where most Playwright-driving code for Workbench lives) because
:func:`quit_vip_sessions_via_ui` backs two callers:

* ``vip_tests.workbench.conftest._cleanup_sessions`` -- the per-test/
  end-of-run safety net that escalates to the UI when the session API
  sweep is unreachable or leaves VIP sessions behind (issue #467).
* ``vip cleanup --workbench-url`` (see :mod:`vip.cli`) -- a standalone CLI
  escape hatch that runs outside of any pytest session.

Keeping one implementation here means both callers share the exact same
selection/quit/retry logic instead of drifting apart.

Note: this module imports :class:`~vip_tests.workbench.pages.Homepage` from
the ``vip_tests`` package for its session-list selectors.  ``vip_tests`` is
shipped as part of the installed ``posit-vip`` distribution (``vip verify``
locates it via ``importlib.util.find_spec("vip_tests")``), so this is not a
test-only import at runtime.  The alternative -- duplicating the raw CSS/XPath
selectors here -- was rejected because ``Homepage`` already tracks
version-specific Workbench UI redesigns (see ``Homepage_2026_05``); a second
copy of those selectors would silently drift out of sync as Workbench's UI
evolves.
"""

from __future__ import annotations

import logging
import re

from playwright.sync_api import Page

from vip.clients.workbench import is_vip_session
from vip.timeouts import timeout_scale
from vip_tests.workbench.pages import Homepage, LoginPage

logger = logging.getLogger(__name__)

# Substrings that mark a Workbench login / IdP URL (mirrors the private
# _LOGIN_KEYWORDS in vip_tests.workbench.conftest).
_LOGIN_URL_KEYWORDS = ("sign-in", "login", "auth")

# Mirrors the scaled timeout constants defined in
# vip_tests/workbench/conftest.py.  Duplicated (not imported) so this module
# has no import-time dependency on the test-fixture module; both are computed
# from the same scaled(...) formula so the values stay numerically identical.
TIMEOUT_QUICK = int(5_000 * timeout_scale())
TIMEOUT_PAGE_LOAD = int(15_000 * timeout_scale())
TIMEOUT_DIALOG_PROBE = int(1_000 * timeout_scale())

_SELECT_PREFIX = "select "


def vip_names_from_select_labels(labels: list[str]) -> list[str]:
    """Extract VIP-named session names from session-row checkbox aria-labels.

    Each homepage session row exposes a checkbox whose aria-label is
    ``"select <session name>"``.  Returns the names (without the ``"select "``
    prefix) that match :func:`is_vip_session`, so a real user's sessions are
    never selected for quitting.  Input order is preserved.
    """
    names: list[str] = []
    for label in labels:
        if not label.startswith(_SELECT_PREFIX):
            continue
        name = label[len(_SELECT_PREFIX) :]
        if is_vip_session(name):
            names.append(name)
    return names


def _complete_sso_if_needed(page: Page) -> bool:
    """Reach the authenticated homepage, completing a silent OIDC SSO if needed.

    On an OIDC-fronted Workbench, loading saved storage state and navigating to
    the site does not land on the homepage: Workbench redirects to its sign-in
    page, which (rather than auto-redirecting to the IdP) renders a "Sign in
    with OpenID" button.  Clicking it completes a silent SSO round-trip using
    the IdP cookies already in the browser context, landing on the
    authenticated homepage with no credentials required.  This is the same
    mechanism ``vip_tests.workbench.conftest.workbench_login`` uses under
    ``--interactive-auth``; reusing it lets ``vip cleanup --workbench-url``
    authenticate the same way the session-launching tests did (issue #467).

    Returns True when the authenticated homepage is loaded (it already was, or
    the SSO click succeeded), False when authentication could not be
    established (e.g. a password form with no username we can fill, or the IdP
    session itself has expired).  Best-effort: never raises.
    """
    logo = page.locator(Homepage.POSIT_LOGO)
    try:
        if logo.is_visible():
            return True  # already authenticated (e.g. the in-test page)
    except Exception:
        pass
    try:
        if not any(kw in page.url.lower() for kw in _LOGIN_URL_KEYWORDS):
            return False  # not on a login page, but no homepage either
    except Exception:
        return False
    # The OIDC sign-in page renders a "Sign in with OpenID" button. Wait briefly
    # so a slow sign-in page is detected reliably rather than raced.
    try:
        sso_button = page.get_by_role("button", name=re.compile(r"sign in", re.IGNORECASE)).first
        sso_button.wait_for(state="visible", timeout=TIMEOUT_QUICK)
    except Exception:
        return False
    # A username field means this is a password form, not silent SSO -- nothing
    # we can complete headlessly, so don't click a blank submit.
    try:
        if page.locator(LoginPage.USERNAME).is_visible():
            return False
    except Exception:
        pass
    try:
        sso_button.click()
        logo.wait_for(state="visible", timeout=TIMEOUT_PAGE_LOAD)
        return True
    except Exception:
        return False  # no valid IdP session to complete SSO silently


def _wait_for_session_list(page: Page) -> None:
    """Wait for the client-rendered session table before enumerating rows.

    The 2026.05+ homepage is a shadcn SPA that fetches and paints the session
    list *after* the page ``load`` event fires, so enumerating the row
    checkboxes immediately after ``goto``/``reload`` can see zero rows even
    when sessions exist -- which made the UI sweep silently no-op and orphan
    sessions (issue #467).  Wait first for the homepage shell (the New Session
    button, present regardless of session count -- this is the same readiness
    signal ``assert_homepage_loaded`` uses), then for the first session-row
    checkbox.  If no checkbox appears within the window the homepage is
    genuinely empty (or still loading), so return quietly and let the caller
    enumerate zero.  Best-effort: never raises.
    """
    for selector in (Homepage.NEW_SESSION_BUTTON, "[aria-label^='select ']"):
        try:
            page.locator(selector).first.wait_for(state="visible", timeout=TIMEOUT_PAGE_LOAD)
        except Exception:
            pass


def quit_vip_sessions_via_ui(page: Page, base_url: str, *, max_iterations: int = 10) -> int:
    """Quit orphaned VIP-named sessions through the homepage UI.

    Fallback for deployments whose session API is unreachable (see
    :meth:`~vip.clients.workbench.WorkbenchClient.sessions_api_reachable`) or
    where the cookie/API sweep is a no-op (the DELETE call "succeeds" without
    actually terminating the session -- issue #467).  Navigates to the
    homepage, selects only VIP-named session rows (validated via
    :func:`is_vip_session`), clicks Quit, and dismisses any
    confirmation/force-quit dialogs, repeating until no VIP rows remain or
    *max_iterations* is hit.  Never uses "Quit All".  Best-effort: all
    Playwright errors are swallowed and it never raises.  Returns the number
    of distinct VIP sessions a quit was issued for (a session that persists
    across iterations is counted once, not per attempt).
    """
    quit_names: set[str] = set()
    first_rows: int | None = None
    first_vip: int | None = None
    try:
        # The session list lives on the homepage at the site root (same URL the
        # tests use via ``page.goto(workbench_url)``), NOT at ``/home`` -- on WB
        # 2026.06 ``/home`` does not render the session table, so the sweep saw
        # zero rows and orphaned sessions (issue #467).
        page.goto(base_url.rstrip("/"), wait_until="load", timeout=TIMEOUT_PAGE_LOAD)
        if not _complete_sso_if_needed(page):
            logger.warning(
                "UI cleanup at %s: could not reach an authenticated homepage "
                "(Workbench redirected to its OIDC sign-in page and the cached session "
                "could not silently complete SSO -- it may have expired). Quit 0 sessions.",
                base_url,
            )
            return 0
        _wait_for_session_list(page)
        for _ in range(max_iterations):
            checkboxes = page.locator("[aria-label^='select ']")
            labels = [
                checkboxes.nth(i).get_attribute("aria-label") or ""
                for i in range(checkboxes.count())
            ]
            vip_names = vip_names_from_select_labels(labels)
            # Record the state on the first pass so the closing summary can
            # report what the sweep actually saw (and whether it cleared it).
            if first_rows is None:
                first_rows = len(labels)
                first_vip = len(vip_names)
            if not vip_names:
                break
            selected: list[str] = []
            for name in vip_names:
                try:
                    page.locator(Homepage.session_checkbox(name)).first.click(timeout=TIMEOUT_QUICK)
                    selected.append(name)
                except Exception as exc:
                    logger.warning(
                        "UI cleanup: could not select session %r at %s: %s", name, base_url, exc
                    )
                    continue
            if not selected:
                break
            try:
                page.locator(Homepage.QUIT_BUTTON).first.click(timeout=TIMEOUT_QUICK)
            except Exception as exc:
                logger.warning(
                    "UI cleanup: could not click the Quit button at %s: %s", base_url, exc
                )
                break
            # Confirm/force-quit dialogs are optional -- a normal quit completes
            # without them (see session_cleaned_up). Probe each within a short
            # window so an absent dialog doesn't dominate runtime; if one does
            # appear, click it with the normal timeout so a present-but-slow
            # dialog still completes (a short click timeout could drop it).
            for sel in (Homepage.CONFIRM_QUIT, Homepage.FORCE_QUIT, Homepage.CONFIRM_FORCE_QUIT):
                dialog = page.locator(sel)
                try:
                    dialog.wait_for(state="visible", timeout=TIMEOUT_DIALOG_PROBE)
                except Exception:
                    continue
                try:
                    dialog.first.click(timeout=TIMEOUT_QUICK)
                except Exception:
                    pass
            quit_names.update(selected)
            try:
                page.reload(wait_until="load", timeout=TIMEOUT_PAGE_LOAD)
            except Exception as exc:
                logger.warning("UI cleanup: could not reload %s after quitting: %s", base_url, exc)
                break
            _complete_sso_if_needed(page)  # a reload can bounce back to sign-in
            _wait_for_session_list(page)
    except Exception as exc:
        logger.warning("UI cleanup at %s failed before completing: %s", base_url, exc)
    # One always-visible summary so the sweep is never a silent black box.
    if first_rows == 0:
        logger.info(
            "UI cleanup at %s: no VIP session rows were visible; nothing to quit.",
            base_url,
        )
    elif first_vip and len(quit_names) < first_vip:
        logger.warning(
            "UI cleanup at %s: found %d VIP session(s) across %d visible row(s) but only "
            "confirmed %d quit; some may still be running.",
            base_url,
            first_vip,
            first_rows,
            len(quit_names),
        )
    else:
        logger.info(
            "UI cleanup at %s: quit %d VIP session(s) (%s row(s) visible).",
            base_url,
            len(quit_names),
            first_rows if first_rows is not None else "?",
        )
    return len(quit_names)
