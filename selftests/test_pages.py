"""Tests for versioned Workbench page-object resolution.

Covers ``get_homepage`` (versioned page-object factory) and
``get_new_session_dialog_close_strategy`` (version-keyed behavior strategy
dict), both in ``vip_tests.workbench.pages.homepage``, plus the cross-build
coverage of the ``RStudioSession`` Workbench Jobs selectors.
"""

from __future__ import annotations

import pytest

from vip.version import ProductVersion
from vip_tests.workbench.pages.homepage import (
    Homepage,
    Homepage_2026_05,
    _close_dialog_via_cancel_button,
    _close_dialog_via_escape,
    get_homepage,
    get_new_session_dialog_close_strategy,
)
from vip_tests.workbench.pages.rstudio_session import RStudioSession


class TestGetHomepage:
    def test_below_threshold_returns_baseline(self):
        assert get_homepage("2026.04.9") is Homepage

    def test_well_below_range_returns_baseline(self):
        assert get_homepage("2020.01.0") is Homepage

    def test_exact_threshold_returns_new_class(self):
        assert get_homepage("2026.05.0") is Homepage_2026_05

    def test_above_threshold_returns_new_class(self):
        assert get_homepage("2027.01.0") is Homepage_2026_05

    def test_accepts_product_version_instance(self):
        assert get_homepage(ProductVersion("2026.05.0")) is Homepage_2026_05
        assert get_homepage(ProductVersion("2026.04.0")) is Homepage

    def test_none_falls_back_to_baseline(self):
        assert get_homepage(None) is Homepage

    def test_unparseable_string_falls_back_to_baseline(self):
        assert get_homepage("not-a-version") is Homepage

    def test_new_class_overrides_only_the_delta(self):
        # Homepage_2026_05 should be a real subclass, inheriting everything
        # else unchanged, and only overriding SESSION_DETAILS_DIALOG.
        assert issubclass(Homepage_2026_05, Homepage)
        assert Homepage_2026_05.SESSION_DETAILS_DIALOG != Homepage.SESSION_DETAILS_DIALOG
        assert Homepage_2026_05.POSIT_LOGO == Homepage.POSIT_LOGO
        assert Homepage_2026_05.NEW_SESSION_BUTTON == Homepage.NEW_SESSION_BUTTON


class TestGetNewSessionDialogCloseStrategy:
    def test_below_threshold_returns_cancel_button_strategy(self):
        assert get_new_session_dialog_close_strategy("2026.04.9") is _close_dialog_via_cancel_button

    def test_exact_threshold_returns_escape_strategy(self):
        assert get_new_session_dialog_close_strategy("2026.05.0") is _close_dialog_via_escape

    def test_above_threshold_returns_escape_strategy(self):
        assert get_new_session_dialog_close_strategy("2027.01.0") is _close_dialog_via_escape

    def test_none_falls_back_to_cancel_button_strategy(self):
        assert get_new_session_dialog_close_strategy(None) is _close_dialog_via_cancel_button

    def test_unparseable_string_falls_back_to_cancel_button_strategy(self):
        assert get_new_session_dialog_close_strategy("garbage") is _close_dialog_via_cancel_button

    def test_strategies_are_callables_accepting_a_page(self):
        import inspect

        for fn in (_close_dialog_via_cancel_button, _close_dialog_via_escape):
            sig = inspect.signature(fn)
            params = list(sig.parameters.values())
            assert len(params) == 1
            assert params[0].name == "page"


@pytest.mark.parametrize("version", ["2026.05.0", "2026.05.1", "2027.01.0"])
def test_resolution_is_consistent_between_factory_and_strategy(version):
    # Both tables share the same 2026.05.0 threshold in this codebase today;
    # confirm they resolve in lockstep for versions at/after it.
    assert get_homepage(version) is Homepage_2026_05
    assert get_new_session_dialog_close_strategy(version) is _close_dialog_via_escape


class TestRStudioSessionWorkbenchJobsSelectors:
    """Lock the Workbench Jobs selectors' cross-build coverage.

    These constants OR-join current and legacy RStudio Pro IDs so the
    ``test_workbench_job`` scenario survives the "workbench_jobs" (underscore)
    vs "workbenchjobs" (no underscore) ID drift documented in the class. The
    selectors are only exercised against a live IDE, so these string-level
    assertions are the only automated guard against a "cleanup" silently
    dropping a variant and reintroducing the false-negative skip.
    """

    def test_tab_matches_both_id_forms(self):
        assert "#rstudio_workbench_tab_workbench_jobs" in RStudioSession.WORKBENCH_JOBS_TAB
        assert "#rstudio_workbench_tab_workbenchjobs" in RStudioSession.WORKBENCH_JOBS_TAB

    def test_panel_matches_both_id_forms(self):
        assert "#rstudio_workbench_panel_workbench_jobs" in RStudioSession.WORKBENCH_JOBS_PANEL
        assert "#rstudio_workbench_panel_workbenchjobs" in RStudioSession.WORKBENCH_JOBS_PANEL

    def test_tab_avoids_substring_match_that_collides_with_panel(self):
        # A substring match such as [id*='workbench_jobs'] would also match the
        # panel id, resolving the tab locator to two elements and tripping
        # Playwright strict mode. Keep the tab locator to exact IDs (plus the
        # text fallback) so it targets exactly one element.
        assert "[id*='workbench_jobs']" not in RStudioSession.WORKBENCH_JOBS_TAB
        assert "[id*='workbenchjobs']" not in RStudioSession.WORKBENCH_JOBS_TAB

    def test_new_button_and_submit_button_target_current_ids(self):
        assert "#rstudio_tb_startworkbenchjob" in RStudioSession.WORKBENCH_JOB_NEW_BUTTON
        assert "Start Workbench Job" in RStudioSession.WORKBENCH_JOB_NEW_BUTTON
        assert "#rstudio_dlg_ok" in RStudioSession.WORKBENCH_JOB_SUBMIT_BUTTON

    def test_script_field_targets_the_readonly_picker_by_id(self):
        # The Workbench Job script field is a readonly FileChooserTextBox; the
        # step must never fill() it. Guard the exact id so a future selector
        # broadening does not accidentally reintroduce the .fill() timeout bug.
        assert RStudioSession.WORKBENCH_JOB_SCRIPT_INPUT == "#rstudio_tbb_text_pro_job_script"

    def test_script_browse_button_targets_current_id(self):
        # Browse... button that opens the Choose File dialog (verified live CDP).
        assert (
            "#rstudio_tbb_button_pro_job_script"
            in RStudioSession.WORKBENCH_JOB_SCRIPT_BROWSE_BUTTON
        )

    def test_file_chooser_selectors_target_current_ids(self):
        assert "#file_dialog_name_prompt" in RStudioSession.FILE_CHOOSER_NAME_INPUT
        assert "#rstudio_file_accept_open" in RStudioSession.FILE_CHOOSER_OPEN_BUTTON
        assert "Open" in RStudioSession.FILE_CHOOSER_OPEN_BUTTON
