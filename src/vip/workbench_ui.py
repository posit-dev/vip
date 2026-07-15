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

from playwright.sync_api import Page

from vip.clients.workbench import is_vip_session
from vip.timeouts import timeout_scale
from vip_tests.workbench.pages import Homepage

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
    try:
        page.goto(base_url.rstrip("/") + "/home", wait_until="load", timeout=TIMEOUT_PAGE_LOAD)
        for _ in range(max_iterations):
            checkboxes = page.locator("[aria-label^='select ']")
            labels = [
                checkboxes.nth(i).get_attribute("aria-label") or ""
                for i in range(checkboxes.count())
            ]
            vip_names = vip_names_from_select_labels(labels)
            if not vip_names:
                break
            selected: list[str] = []
            for name in vip_names:
                try:
                    page.locator(Homepage.session_checkbox(name)).first.click(timeout=TIMEOUT_QUICK)
                    selected.append(name)
                except Exception:
                    continue
            if not selected:
                break
            try:
                page.locator(Homepage.QUIT_BUTTON).first.click(timeout=TIMEOUT_QUICK)
            except Exception:
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
            except Exception:
                break
    except Exception:
        pass
    return len(quit_names)
