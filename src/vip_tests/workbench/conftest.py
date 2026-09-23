"""Workbench-specific fixtures and helpers.

Page selectors are in the pages/ subpackage

The helpers live in the sibling ``login``, ``sessions``, ``naming``,
``cleanup``, ``capacity`` and ``timeouts`` modules. This file keeps the
IDE-launch skip-cascade hooks, ``wb_login``, the shared Given step and
``shiny_bundle_spec``, and imports every fixture those modules define so
pytest discovers them (a non-root ``conftest.py`` cannot use
``pytest_plugins``). It also re-exports the names step files and selftests
import from here. Patch a helper on the module that calls it, not here: a
re-export does not change the global the module looks up.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Page
from pytest_bdd import given

from vip.plugin import _auth_session_key

# Re-exported for selftests/test_workbench_cleanup.py, which imports it from
# here (not from vip.workbench_ui directly) to match the pre-move layout.
from vip.workbench_ui import (
    vip_names_from_select_labels as _vip_names_from_select_labels,
)
from vip_tests.connect.bundles import _SHINY_APP_R, _latest_version, manifest_raw_url
from vip_tests.workbench.capacity import (
    MAX_AUTO_DETECTED_PROFILES,
    ResourceProfileDisabledError,
    _option_is_disabled,
    cap_auto_detected_profiles,
    profile_size_key,
)
from vip_tests.workbench.cleanup import (
    _cleanup_sessions,
    _quit_vip_sessions_via_ui,
    _run_session_cleanup,
    _session_api_reachable_via_cookies,
    _wb_cleanup_state,
    quit_owned_sessions_via_page,
)
from vip_tests.workbench.login import (
    _external_idp_host,
    _login_lock_path,
    _navigated_into_session,
    _silent_sso_signin,
    oidc_login_lock,
    restore_shared_session,
    workbench_login,
)
from vip_tests.workbench.naming import (
    capacity_session_prefix,
    current_worker_id,
    k8s_session_prefix,
    unique_session_name,
    vip_session_prefix,
)
from vip_tests.workbench.sessions import (
    _session_failure_message,
    _session_timeout_message,
    _skip_workbench_session_unproven,
    _workbench_session_skip_message,
    assert_homepage_loaded,
    format_capacity_failure,
    raise_if_session_failed,
    wait_for_session_active,
    wait_for_session_suspended,
)
from vip_tests.workbench.timeouts import (
    TERMINAL_SESSION_FAILURE_STATES,
    TIMEOUT_CLEANUP,
    TIMEOUT_CODE_EXEC,
    TIMEOUT_DIALOG,
    TIMEOUT_DIALOG_PROBE,
    TIMEOUT_IDE_LOAD,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_QUICK,
    TIMEOUT_SESSION_START,
    TIMEOUT_SSO_ROUNDTRIP,
)

__all__ = [
    "MAX_AUTO_DETECTED_PROFILES",
    "ResourceProfileDisabledError",
    "TERMINAL_SESSION_FAILURE_STATES",
    "TIMEOUT_CLEANUP",
    "TIMEOUT_CODE_EXEC",
    "TIMEOUT_DIALOG",
    "TIMEOUT_DIALOG_PROBE",
    "TIMEOUT_IDE_LOAD",
    "TIMEOUT_PAGE_LOAD",
    "TIMEOUT_QUICK",
    "TIMEOUT_SESSION_START",
    "TIMEOUT_SSO_ROUNDTRIP",
    "_cleanup_sessions",
    "_external_idp_host",
    "_login_lock_path",
    "_navigated_into_session",
    "_option_is_disabled",
    "_quit_vip_sessions_via_ui",
    "_run_session_cleanup",
    "_session_api_reachable_via_cookies",
    "_session_failure_message",
    "_session_timeout_message",
    "_silent_sso_signin",
    "_skip_workbench_session_unproven",
    "_vip_names_from_select_labels",
    "_wb_cleanup_state",
    "_workbench_session_skip_message",
    "assert_homepage_loaded",
    "cap_auto_detected_profiles",
    "capacity_session_prefix",
    "current_worker_id",
    "format_capacity_failure",
    "k8s_session_prefix",
    "oidc_login_lock",
    "profile_size_key",
    "quit_owned_sessions_via_page",
    "raise_if_session_failed",
    "restore_shared_session",
    "unique_session_name",
    "vip_session_prefix",
    "wait_for_session_active",
    "wait_for_session_suspended",
    "workbench_login",
]

pytestmark = [pytest.mark.workbench, pytest.mark.xdist_group("workbench")]


_IDE_MARKERS = ("rstudio", "vscode", "jupyter", "positron")

# Human-readable names for the _IDE_MARKERS, used in skip messages (#592).
_IDE_DISPLAY_NAMES: dict[str, str] = {
    "rstudio": "RStudio",
    "vscode": "VS Code",
    "jupyter": "JupyterLab",
    "positron": "Positron",
}

# Records each IDE's test_ide_launch.py outcome ("passed" / "failed" / "skipped")
# so test_ide_extensions.py can skip the extension checks for an IDE whose
# launch test did not pass, instead of rediscovering "this IDE isn't
# available" the expensive way -- launching a session and timing out after
# TIMEOUT_SESSION_START (~90s). See pytest_runtest_makereport below and the
# autouse fixture in test_ide_extensions.py (#592).
_ide_launch_outcome_key = pytest.StashKey[dict[str, str]]()


def _workbench_group_name(ide_markers: set[str], module_stem: str) -> str:
    """Compute the xdist group for a Workbench test under shared auth (hybrid grouping).

    Any scenario carrying an IDE marker -- launch and extensions alike -- groups by IDE so
    each IDE runs on its own worker: ``workbench_ide_<ide>``. That is what puts an IDE's
    launch and extension tests on the same worker. Every other Workbench test groups by
    feature module: ``workbench_<stem>`` (a leading ``test_`` stripped).

    Raises ``pytest.UsageError`` if *ide_markers* carries more than one IDE marker,
    mirroring the guard in ``test_ide_extensions.py``'s
    ``_skip_if_ide_launch_did_not_pass`` fixture -- rather than silently picking
    whichever marker happens to come first in ``_IDE_MARKERS`` order.
    """
    if len(ide_markers) > 1:
        raise pytest.UsageError(
            f"Expected at most one IDE marker in {_IDE_MARKERS}, got {sorted(ide_markers)}"
        )
    for ide in _IDE_MARKERS:
        if ide in ide_markers:
            return f"workbench_ide_{ide}"
    stem = module_stem[len("test_") :] if module_stem.startswith("test_") else module_stem
    return f"workbench_{stem}"


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Group Workbench tests for parallel execution when a shared auth session is active.

    Under --interactive-auth / --headless-auth all Workbench tests authenticate as the same
    shared account. Rather than pin them all to one worker (the old serial workaround), we
    group them so LoadGroupScheduling spreads them across workers: IDE-launch scenarios by
    IDE (``workbench_ide_<ide>``), everything else by feature module (``workbench_<module>``).
    The simultaneous-login storm this used to cause is prevented by the cross-worker login
    lock in :func:`workbench_login` (see :func:`oidc_login_lock`), not by serialization.

    Password / no-auth runs are left untouched: they hit the early return below, so their
    Workbench items keep the default ``workbench`` group that ``plugin.py``'s
    :func:`_assign_xdist_group` directory fallback assigns (the module-level ``pytestmark``
    at the top of this file does not propagate to sibling test modules, so it assigns
    nothing here).
    """
    if config.stash.get(_auth_session_key, None) is None:
        # No shared auth session — password auth or no auth. Keep default parallel behavior.
        return

    workbench_dir = Path(__file__).parent
    for item in items:
        item_path = getattr(item, "path", None)
        if item_path is None or not item_path.is_relative_to(workbench_dir):
            continue
        ide_markers = {m.name for m in item.iter_markers()} & set(_IDE_MARKERS)
        group = _workbench_group_name(ide_markers, item_path.stem)
        # Strip any pre-existing xdist_group marker before adding the hybrid group. No
        # per-test xdist_group marker exists today, so this is a defensive guard: xdist
        # concatenates *all* xdist_group marks on an item (via iter_markers), it does not
        # take the closest, so a leftover mark would corrupt the group name rather than be
        # shadowed. plugin.py's _assign_xdist_group then respects the group we add here.
        item.own_markers = [m for m in item.own_markers if m.name != "xdist_group"]
        item.add_marker(pytest.mark.xdist_group(group))


def _record_ide_launch_outcome(outcomes: dict[str, str], ide: str, new_outcome: str) -> None:
    """Merge *new_outcome* into *outcomes* for *ide*, keeping the "worst" result.

    A later phase is never allowed to overwrite a recorded non-passed outcome
    with "passed" -- a launch that skipped or failed at an earlier phase must
    not look like it passed just because a later phase did. Any other
    transition (first record, or a later phase that is itself non-passed)
    simply overwrites.
    """
    previous = outcomes.get(ide)
    if previous is not None and previous != "passed" and new_outcome == "passed":
        return
    outcomes[ide] = new_outcome


def _ide_extension_skip_reason(ide: str, outcome: str | None) -> str | None:
    """Return the skip reason for *ide*'s recorded launch *outcome*, or ``None`` to run.

    Absence of a recorded outcome (*outcome* is ``None``) always returns
    ``None`` (run) -- this is the "absence means run" rule from #592: the
    launch tests may have been deselected (``--basic`` drops ``@slow``),
    ``test_ide_extensions.py`` may be run standalone, or the stash may simply
    be empty on this worker. Only a positive "it did not pass" (a recorded,
    non-``"passed"`` outcome) returns a skip reason.
    """
    if outcome is None or outcome == "passed":
        return None
    display = _IDE_DISPLAY_NAMES.get(ide, ide)
    return f"{display} launch did not pass ({outcome}) — skipping extension checks"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call):
    """Record each IDE-launch scenario's outcome for the extensions cascade skip.

    Only ``test_ide_launch.py`` items carrying one of ``_IDE_MARKERS`` are
    recorded (the hybrid grouping above puts an IDE's launch and extensions
    scenarios in the same xdist group, so they always land on the same
    worker -- the same process whose stash this reads back from). Both the
    ``setup`` and ``call`` phases are recorded, so an "IDE not configured"
    skip raised during setup (see ``_dismiss_dialog_and_skip``) is captured
    even though ``call`` never runs -- see :func:`_record_ide_launch_outcome`
    for the merge rule.
    """
    outcome = yield
    report: pytest.TestReport = outcome.get_result()
    if report.when not in ("setup", "call"):
        return
    item_path = getattr(item, "path", None)
    if item_path is None or item_path.name != "test_ide_launch.py":
        return
    ide_markers = {m.name for m in item.iter_markers()} & set(_IDE_MARKERS)
    if not ide_markers:
        return
    outcomes = item.config.stash.setdefault(_ide_launch_outcome_key, {})
    for ide in ide_markers:
        _record_ide_launch_outcome(outcomes, ide, report.outcome)


def extract_repo_urls(output: str) -> list[str]:
    """Extract URLs from R's ``getOption('repos')`` console output.

    ``IGNORECASE`` on the scheme: R can echo the scheme in whatever case the
    repos config carries (e.g. ``HTTPS://...``); without it, a scheme-cased
    URL is silently dropped here before ``pm_url_matches_repo_urls`` ever gets
    a chance to apply its own case-insensitive scheme/host comparison, making
    that comparison unreachable for exactly the input it exists to handle.
    """
    return re.findall(r"https?://[^\s<>\"']+", output, re.IGNORECASE)


@pytest.fixture
def wb_login(
    page: Page,
    workbench_url: str,
    test_username: str,
    test_password: str,
    auth_provider: str,
    interactive_auth: bool,
    auth_mode: str,
    workbench_auth_error: str | None,
):
    """Log in to Workbench and verify homepage loads.

    This fixture handles the complete login flow using rstudio-pro patterns.
    Handles password auth, OIDC via pre-loaded storage state (--interactive-auth /
    --headless-auth), and skips gracefully when auth type is unsupported.

    Returns the page for further interactions.
    """
    workbench_login(
        page,
        workbench_url,
        test_username,
        test_password,
        auth_provider,
        interactive_auth,
        auth_mode=auth_mode,
        workbench_auth_error=workbench_auth_error,
    )

    assert_homepage_loaded(page)

    return page


# ---------------------------------------------------------------------------
# Shared BDD steps
# ---------------------------------------------------------------------------


@given("Workbench is accessible and I am logged in")
def workbench_accessible_and_logged_in(
    page: Page,
    workbench_url: str,
    test_username: str,
    test_password: str,
    auth_provider: str,
    interactive_auth: bool,
    auth_mode: str,
    workbench_auth_error: str | None,
):
    workbench_login(
        page,
        workbench_url,
        test_username,
        test_password,
        auth_provider,
        interactive_auth,
        auth_mode=auth_mode,
        workbench_auth_error=workbench_auth_error,
    )
    assert_homepage_loaded(page)


# ---------------------------------------------------------------------------
# Bundle fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def shiny_bundle_spec(connect_client) -> dict[str, str]:
    """Coordinates for materializing the shared R Shiny bundle in a session.

    Returns the pieces the deploy step needs to reconstruct -- inside the
    Workbench session's own filesystem -- the *same* bundle the Connect deploy
    test uses:

    - ``app_r``: the minimal ``app.R`` (``fluidPage("VIP test")`` + empty
      server), small enough to type into the terminal.  Its MD5 is the checksum
      baked into ``shiny_manifest.json``.
    - ``manifest_url``: raw URL of the reference ``shiny_manifest.json`` in the
      public repo, pinned to the installed VIP version's tag.  The manifest
      carries the full 30-package dependency closure (~80 KB), far too large to
      type reliably through the terminal, so the session downloads it directly.
    - ``manifest_url_fallback``: the same raw URL at ``main``.  A dev/unreleased
      checkout (version bumped, tag not yet pushed) 404s on the tag; the deploy
      script falls back to this before concluding the manifest is unreachable.
    - ``platform``: the newest R installed on Connect, patched into the
      downloaded manifest exactly as ``build_shiny_bundle_files`` does, so the
      Workbench and Connect bundles stay identical.

    Skips when Connect is unavailable or has no R installed (the manifest
    ``platform`` must match a real server R version).  The download itself may
    also fail at deploy time (firewalled session) -- that is handled in the step
    as a skip, since it is an environment constraint, not a publishing defect.
    """
    from vip import __version__

    if connect_client is None:
        pytest.skip("Connect is not configured — cannot build the shared Shiny bundle")
    r_versions = connect_client.r_versions()
    if not r_versions:
        pytest.skip("No R versions available on Connect — cannot build the Shiny bundle")
    return {
        "app_r": _SHINY_APP_R,
        "manifest_url": manifest_raw_url(f"v{__version__}"),
        "manifest_url_fallback": manifest_raw_url("main"),
        "platform": _latest_version(r_versions),
    }
