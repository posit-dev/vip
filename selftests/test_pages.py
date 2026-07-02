"""Tests for versioned Workbench page-object resolution.

Covers ``get_homepage`` (versioned page-object factory) and
``get_new_session_dialog_close_strategy`` (version-keyed behavior strategy
dict), both in ``vip_tests.workbench.pages.homepage``.
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
