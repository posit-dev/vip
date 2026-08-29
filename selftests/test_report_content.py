"""Tests for vip.report_content — the format-neutral layer under both backends.

``vip.report_html`` and ``vip.report_typst`` share every decision made here:
card titles and ``<param>`` substitution, outcome and marker styling,
grouping, Gherkin step lookup, skip wording, and provenance rows. A bug in
this module reaches both the browsable report and the archived PDF, so it is
tested on its own rather than only through one backend's markup.

``TestBadgeColors`` is the drift guard: badge colors live here *and* in
``report/styles.css``, because Typst has no stylesheet to read.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import matrix_from_statuses
from vip import report_content
from vip.reporting import ReportData, TestResult

# ---------------------------------------------------------------------------
# <param> placeholder substitution
# ---------------------------------------------------------------------------


class TestSubstituteParamPlaceholders:
    def test_no_placeholder_returns_title_unchanged(self):
        assert report_content.substitute_param_placeholders("a.py::test_x", "Plain title") == (
            "Plain title"
        )

    def test_substitutes_placeholder_from_nodeid_suffix(self):
        title = report_content.substitute_param_placeholders(
            "test_pkg.py::test_install[cran]", "Install <repo> package"
        )
        assert title == "Install cran package"

    def test_no_param_suffix_leaves_placeholder(self):
        title = report_content.substitute_param_placeholders(
            "test_pkg.py::test_install", "Install <repo> package"
        )
        assert title == "Install <repo> package"

    def test_display_title_falls_back_to_bare_function_name(self):
        item = TestResult(nodeid="src/vip_tests/connect/test_x.py::test_login", outcome="passed")
        assert report_content.display_title(item) == "test_login"

    def test_display_title_prefers_scenario_title(self):
        item = TestResult(
            nodeid="a.py::test_x[cran]",
            outcome="passed",
            scenario_title="Install <repo> package",
        )
        assert report_content.display_title(item) == "Install cran package"


# ---------------------------------------------------------------------------
# Outcome styling
# ---------------------------------------------------------------------------


class TestOutcomeStyle:
    def test_unknown_status_degrades_to_grey_placeholder(self):
        style = report_content.outcome_style("weird")
        assert style.label == "?"

    @pytest.mark.parametrize(
        ("status", "label"),
        [("passed", "PASS"), ("failed", "FAIL"), ("skipped", "SKIP"), ("na_version", "N/A")],
    )
    def test_known_statuses_have_their_own_label(self, status, label):
        assert report_content.outcome_style(status).label == label

    def test_summary_status_is_fail_when_anything_failed(self):
        data = ReportData(results=[TestResult(nodeid="a", outcome="failed")])
        assert report_content.summary_status(data) == "FAIL"

    def test_summary_status_is_pass_with_no_failures(self):
        data = ReportData(results=[TestResult(nodeid="a", outcome="passed")])
        assert report_content.summary_status(data) == "PASS"


# ---------------------------------------------------------------------------
# Badge colors — the styles.css drift guard
# ---------------------------------------------------------------------------

_STYLESHEET = Path(__file__).resolve().parent.parent / "report" / "styles.css"


def _stylesheet_color(css: str, selector: str, prop: str) -> str | None:
    """The ``prop`` value ``css`` declares for ``selector``.

    Every badge class appears in ``styles.css`` twice — once in the grouped
    rule that sets the shared pill layout, once in its own rule that sets the
    color — so this scans every block for the class and returns the property
    from whichever one declares it.
    """
    for match in re.finditer(rf"^\.{re.escape(selector)}\s*\{{(.*?)\}}", css, re.S | re.M):
        declared = re.search(rf"{re.escape(prop)}:\s*([^;]+);", match.group(1))
        if declared:
            return declared.group(1).strip()
    return None


class TestBadgeColors:
    """Every ``Badge.color`` must equal the one ``styles.css`` paints.

    The HTML report gets its badge colors from the stylesheet and the PDF
    cannot, so ``report_content`` carries a second copy. These tests fail when
    the copies disagree, which is the only thing keeping the two reports
    looking alike.
    """

    @pytest.fixture(scope="class")
    def css(self) -> str:
        return _STYLESHEET.read_text()

    @pytest.mark.parametrize("marker", sorted(report_content.PRIMARY_BADGES))
    def test_primary_badge_color_matches_stylesheet(self, css, marker):
        badge = report_content.PRIMARY_BADGES[marker]
        assert _stylesheet_color(css, badge.css_class, "background-color") == badge.color

    def test_secondary_badges_match_stylesheet(self, css):
        # Every secondary badge shares one grouped rule, so read it once.
        rule = re.search(r"\.badge-ide,\s*\.badge-slow\s*\{(.*?)\}", css, re.S)
        assert rule, "the grouped .badge-ide/.badge-slow rule is gone from styles.css"
        body = rule.group(1)
        for badge in report_content.SECONDARY_BADGES.values():
            assert f"color: {badge.color};" in body
        assert f"background: {report_content.SECONDARY_BADGE_BACKGROUND};" in body
        assert report_content.SECONDARY_BADGE_BORDER in body

    def test_every_primary_badge_has_a_stylesheet_rule(self, css):
        # A new badge added to Python but not to the stylesheet renders
        # unstyled in HTML while looking correct in the PDF.
        for badge in report_content.PRIMARY_BADGES.values():
            assert f".{badge.css_class}" in css


# ---------------------------------------------------------------------------
# Feature description (F4)
# ---------------------------------------------------------------------------


class TestDominantFeatureDescription:
    def test_majority_value_is_dominant(self):
        results = [
            TestResult(nodeid="a", outcome="passed", feature_description="As a Posit Team admin"),
            TestResult(nodeid="b", outcome="passed", feature_description="As a Posit Team admin"),
            TestResult(nodeid="c", outcome="passed", feature_description="As a VIP user"),
        ]
        assert report_content.dominant_feature_description(results) == "As a Posit Team admin"

    def test_no_descriptions_returns_none(self):
        results = [TestResult(nodeid="a", outcome="passed")]
        assert report_content.dominant_feature_description(results) is None

    def test_dominant_description_is_suppressed(self):
        item = TestResult(nodeid="a", outcome="passed", feature_description="As a Posit admin")
        assert report_content.description_line(item, dominant="As a Posit admin") == ""

    def test_differing_description_is_kept(self):
        item = TestResult(nodeid="a", outcome="passed", feature_description="As a VIP user")
        assert report_content.description_line(item, dominant="As a Posit admin") == "As a VIP user"

    def test_missing_description_returns_empty(self):
        item = TestResult(nodeid="a", outcome="passed", feature_description=None)
        assert report_content.description_line(item, dominant="anything") == ""


# ---------------------------------------------------------------------------
# Skip wording (F3)
# ---------------------------------------------------------------------------


class TestSkipReasonParts:
    def test_passed_test_has_no_skip_wording(self):
        item = TestResult(nodeid="a", outcome="passed")
        assert report_content.skip_reason_parts(item) == ("", "")

    def test_ordinary_skip_uses_its_recorded_reason(self):
        item = TestResult(nodeid="a", outcome="skipped", skip_reason="Connect not configured")
        assert report_content.skip_reason_parts(item) == ("Connect not configured", "")

    def test_missing_reason_falls_back_to_placeholder(self):
        item = TestResult(nodeid="a", outcome="skipped", skip_reason=None)
        assert report_content.skip_reason_parts(item) == ("No reason recorded.", "")

    def test_whitespace_only_reason_falls_back_to_placeholder(self):
        item = TestResult(nodeid="a", outcome="skipped", skip_reason="   ")
        assert report_content.skip_reason_parts(item) == ("No reason recorded.", "")

    def test_na_version_leads_with_the_plain_english_explanation(self):
        item = TestResult(
            nodeid="a",
            outcome="skipped",
            na_version=True,
            skip_reason="connect version unknown for min_version 2024.09.0",
        )
        explanation, detail = report_content.skip_reason_parts(item)
        assert explanation == report_content.NA_VERSION_EXPLANATION
        assert detail == "connect version unknown for min_version 2024.09.0"

    def test_na_version_without_detail_keeps_the_explanation(self):
        item = TestResult(nodeid="a", outcome="skipped", na_version=True, skip_reason=None)
        explanation, detail = report_content.skip_reason_parts(item)
        assert explanation == report_content.NA_VERSION_EXPLANATION
        assert detail == ""


# ---------------------------------------------------------------------------
# category_for / group_by_category / rollup
# ---------------------------------------------------------------------------


class TestCategoryFor:
    """category_for prefers a scenario's own marker over the directory it
    lives in, falling back to TestResult.category (which derives the category
    from the nodeid path)."""

    def test_real_nodeid_shape_resolves_to_directory(self):
        item = TestResult(nodeid="src/vip_tests/connect/test_auth.py::test_login", outcome="passed")
        assert item.category == "connect"
        assert report_content.category_for(item) == "connect"

    def test_marker_match_takes_priority_over_path_scan(self):
        # A cross-cutting test physically under workbench/ but tagged @connect.
        item = TestResult(
            nodeid="src/vip_tests/workbench/test_publish.py::test_x",
            outcome="passed",
            markers=["connect"],
        )
        assert report_content.category_for(item) == "connect"

    def test_no_marker_and_no_known_path_segment_falls_back_to_category(self):
        item = TestResult(nodeid="tests/unknown/test_x.py::test_y", outcome="passed")
        assert report_content.category_for(item) == item.category

    def test_group_by_category_buckets_correctly(self):
        results = [
            TestResult(nodeid="src/vip_tests/connect/test_a.py::t1", outcome="passed"),
            TestResult(nodeid="src/vip_tests/workbench/test_b.py::t2", outcome="passed"),
            TestResult(nodeid="src/vip_tests/connect/test_c.py::t3", outcome="failed"),
        ]
        groups = report_content.group_by_category(results)
        assert len(groups["connect"]) == 2
        assert len(groups["workbench"]) == 1

    def test_results_for_product_counts_a_dual_tagged_scenario_twice(self):
        item = TestResult(nodeid="a.py::t", outcome="passed", markers=["connect", "workbench"])
        assert report_content.results_for_product([item], "connect") == [item]
        assert report_content.results_for_product([item], "workbench") == [item]

    def test_category_label_titlecases_and_unslugs(self):
        assert report_content.category_label("package_manager") == "Package Manager"


class TestOutcomeCountsSummary:
    def test_lists_only_non_zero_outcomes_in_fixed_order(self):
        results = [
            TestResult(nodeid="a", outcome="passed"),
            TestResult(nodeid="b", outcome="passed"),
            TestResult(nodeid="c", outcome="failed"),
        ]
        assert report_content.outcome_counts_summary(results) == "2 passed, 1 failed"

    def test_na_version_gets_its_own_label(self):
        results = [TestResult(nodeid="a", outcome="skipped", na_version=True)]
        assert report_content.outcome_counts_summary(results) == "1 N/A (version)"


class TestPluralize:
    def test_one_is_singular(self):
        assert report_content.pluralize(1) == "1 test"

    def test_zero_and_many_are_plural(self):
        assert report_content.pluralize(0) == "0 tests"
        assert report_content.pluralize(3) == "3 tests"


# ---------------------------------------------------------------------------
# Provenance (F9)
# ---------------------------------------------------------------------------


class TestProvenanceRows:
    def test_absent_fields_come_back_as_none(self):
        rows = dict(report_content.provenance_rows(ReportData()))
        assert rows["VIP version"] is None
        assert rows["Run duration"] is None
        assert rows["Mode"] is None

    def test_recorded_fields_are_formatted(self):
        data = ReportData(
            vip_version="2026.8.3",
            run_duration_seconds=12.34,
            python_version="3.13.1",
            platform="Linux",
            basic_mode=True,
            exit_status=0,
        )
        rows = dict(report_content.provenance_rows(data))
        assert rows["VIP version"] == "2026.8.3"
        assert rows["Run duration"] == "12.3s"
        assert rows["Mode"] == "basic"
        assert rows["Exit status"] == "0 (OK — no failures)"

    def test_full_mode_is_labelled_full(self):
        rows = dict(report_content.provenance_rows(ReportData(basic_mode=False)))
        assert rows["Mode"] == "full"

    def test_unrecognized_exit_code_says_so(self):
        rows = dict(report_content.provenance_rows(ReportData(exit_status=99)))
        assert rows["Exit status"] == "99 (unrecognized exit code)"


# ---------------------------------------------------------------------------
# Steps lookup (feature file resolution)
# ---------------------------------------------------------------------------


class TestFeatureStepIndex:
    def test_missing_feature_file_returns_empty_list(self):
        index = report_content.FeatureStepIndex()
        item = TestResult(nodeid="vip_tests/nope/test_missing.py::test_x", outcome="passed")
        assert index.steps_for(item) == []

    def test_no_scenario_title_returns_empty_list(self):
        index = report_content.FeatureStepIndex()
        item = TestResult(nodeid="a.py::test_x", outcome="passed", scenario_title=None)
        assert index.steps_for(item) == []


# ---------------------------------------------------------------------------
# Coverage display (failing controls)
# ---------------------------------------------------------------------------


class TestFailedControlDisplay:
    def test_a_failing_control_displays_as_covered_failed(self):
        entry = SimpleNamespace(coverage="covered", executed=True, failing=True)
        assert report_content.display_coverage(entry) == "covered_failed"

    def test_a_failing_control_uses_the_failed_style(self):
        """Reuses the outcome palette so the styles.css drift guard still holds."""
        assert report_content.COVERAGE_STYLE_KEY["covered_failed"] == "failed"

    def test_a_failing_control_is_labelled_failed(self):
        assert report_content.COVERAGE_LABELS["covered_failed"] == "FAILED"

    def test_a_passing_control_still_displays_as_covered(self):
        entry = SimpleNamespace(coverage="covered", executed=True, failing=False)
        assert report_content.display_coverage(entry) == "covered"

    def test_an_all_skipped_control_still_displays_as_not_executed(self):
        entry = SimpleNamespace(coverage="covered", executed=False, failing=False)
        assert report_content.display_coverage(entry) == "covered_not_executed"

    def test_a_gap_is_unaffected(self):
        entry = SimpleNamespace(coverage="gap", executed=False, failing=False)
        assert report_content.display_coverage(entry) == "gap"

    def test_every_coverage_value_has_a_style_and_a_label(self):
        assert set(report_content.COVERAGE_STYLE_KEY) == set(report_content.COVERAGE_LABELS)

    def test_a_real_mixed_pass_and_failure_control_displays_as_failed(self):
        """End to end through a real matrix, not a stub.

        The stub tests above assert display_coverage's branching. This asserts
        the decision the branching exists to implement: one failing scenario
        demotes a control that also has a passing one.
        """
        matrix = matrix_from_statuses({"c1": ["passed", "failed"]})
        entry = matrix.entries[0]
        assert entry.coverage == "covered"
        assert report_content.display_coverage(entry) == "covered_failed"

    def test_a_real_mixed_control_is_counted_in_the_summary(self):
        """The summary row reads the display value, so the count must follow."""
        matrix = matrix_from_statuses({"c1": ["passed", "failed"], "c2": ["passed"]})
        rows = dict(report_content.traceability_summary_rows(matrix))
        assert rows["Covered, failing"] == "1"
        assert rows["Covered and executed"] == "1"


class TestTraceabilityWarnings:
    def test_a_failing_control_produces_a_warning(self):
        matrix = SimpleNamespace(covered_without_execution=[], covered_with_failure=["c1"])
        warnings_out = report_content.traceability_warnings(matrix)
        assert any("did not pass" in w and "c1" in w for w in warnings_out)

    def test_both_conditions_produce_two_warnings(self):
        matrix = SimpleNamespace(covered_without_execution=["c2"], covered_with_failure=["c1"])
        assert len(report_content.traceability_warnings(matrix)) == 2

    def test_a_clean_matrix_produces_none(self):
        matrix = SimpleNamespace(covered_without_execution=[], covered_with_failure=[])
        assert report_content.traceability_warnings(matrix) == []
