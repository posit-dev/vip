"""Tests for vip.report_html — the HTML rendering sibling of vip.reporting.

Covers escaping (the security property that matters most, since this
renders into a publicly published report), card rendering per outcome
including the skip-reason/na_version paths, per-product counts, the
``<param>`` substitution, graceful handling of ``None`` provenance, and
empty results.
"""

from __future__ import annotations

from vip import report_html
from vip.reporting import ProductInfo, ReportData, TestResult

# ---------------------------------------------------------------------------
# <param> placeholder substitution
# ---------------------------------------------------------------------------


class TestSubstituteParamPlaceholders:
    def test_no_placeholder_returns_title_unchanged(self):
        assert report_html.substitute_param_placeholders("a.py::test_x", "Plain title") == (
            "Plain title"
        )

    def test_substitutes_placeholder_from_nodeid_suffix(self):
        title = report_html.substitute_param_placeholders(
            "test_pkg.py::test_install[cran]", "Install <repo> package"
        )
        assert title == "Install cran package"

    def test_no_param_suffix_leaves_placeholder(self):
        title = report_html.substitute_param_placeholders(
            "test_pkg.py::test_install", "Install <repo> package"
        )
        assert title == "Install <repo> package"

    def test_display_title_falls_back_to_bare_function_name(self):
        item = TestResult(nodeid="src/vip_tests/connect/test_x.py::test_login", outcome="passed")
        assert report_html.display_title(item) == "test_login"

    def test_display_title_prefers_scenario_title(self):
        item = TestResult(
            nodeid="a.py::test_x[cran]",
            outcome="passed",
            scenario_title="Install <repo> package",
        )
        assert report_html.display_title(item) == "Install cran package"


# ---------------------------------------------------------------------------
# Escaping — the security property
# ---------------------------------------------------------------------------


class TestEscaping:
    """Every value that reaches the returned HTML must be escaped."""

    DANGEROUS = "<script>alert(1)</script> & \"quoted\" & 'single'"

    def test_card_title_is_escaped(self):
        item = TestResult(
            nodeid="a.py::test_x",
            outcome="passed",
            scenario_title=self.DANGEROUS,
        )
        html = report_html.render_card(
            item,
            index=0,
            feature_index=report_html.FeatureStepIndex(),
            hints={},
            dominant_description=None,
        )
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_nodeid_is_escaped(self):
        item = TestResult(nodeid=f"a.py::{self.DANGEROUS}", outcome="passed")
        html = report_html.render_card(
            item,
            index=0,
            feature_index=report_html.FeatureStepIndex(),
            hints={},
            dominant_description=None,
        )
        assert "<script>alert(1)</script>" not in html

    def test_concise_error_is_escaped(self):
        item = TestResult(
            nodeid="a.py::test_x",
            outcome="failed",
            concise_error=self.DANGEROUS,
        )
        html = report_html.error_html(item, "vip-error-0")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_longrepr_is_escaped(self):
        item = TestResult(
            nodeid="a.py::test_x",
            outcome="failed",
            longrepr=self.DANGEROUS,
        )
        html = report_html.error_html(item, "vip-error-0")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_skip_reason_is_escaped(self):
        item = TestResult(
            nodeid="a.py::test_x",
            outcome="skipped",
            skip_reason=self.DANGEROUS,
        )
        html = report_html.skip_reason_html(item)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_feature_description_is_escaped(self):
        item = TestResult(
            nodeid="a.py::test_x",
            outcome="passed",
            feature_description=self.DANGEROUS,
        )
        html = report_html.description_html(item, dominant="something else")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_hint_content_is_escaped(self):
        item = TestResult(
            nodeid="a.py::test_x",
            outcome="failed",
            scenario_title="My scenario",
        )
        hints = {
            "My scenario": {
                "likely_causes": [self.DANGEROUS],
                "suggested_steps": [self.DANGEROUS],
                "docs_url": "https://example.com/?x=" + self.DANGEROUS,
            }
        }
        html = report_html.hints_html(item, hints)
        assert "<script>alert(1)</script>" not in html
        assert html.count("&lt;script&gt;") >= 2

    def test_quotes_and_ampersand_are_escaped_in_card(self):
        item = TestResult(
            nodeid="a.py::test_x",
            outcome="passed",
            scenario_title="Title with \"quotes\" & 'apostrophes'",
        )
        html = report_html.render_card(
            item,
            index=0,
            feature_index=report_html.FeatureStepIndex(),
            hints={},
            dominant_description=None,
        )
        assert '"quotes"' not in html
        assert "&quot;quotes&quot;" in html
        assert "&amp;" in html
        assert "&#x27;apostrophes&#x27;" in html


# ---------------------------------------------------------------------------
# Card rendering per outcome
# ---------------------------------------------------------------------------


class TestRenderCard:
    def _card(self, item: TestResult, hints: dict | None = None) -> str:
        return report_html.render_card(
            item,
            index=0,
            feature_index=report_html.FeatureStepIndex(),
            hints=hints or {},
            dominant_description=None,
        )

    def test_passed_card_shows_pass_badge(self):
        item = TestResult(nodeid="a.py::test_x", outcome="passed")
        html = self._card(item)
        assert ">PASS<" in html
        assert "vip-fail-concise" not in html

    def test_failed_card_shows_fail_badge_and_concise_error(self):
        item = TestResult(
            nodeid="a.py::test_x",
            outcome="failed",
            concise_error="AssertionError: boom",
        )
        html = self._card(item)
        assert ">FAIL<" in html
        assert "AssertionError: boom" in html
        assert "vip-fail-concise" in html

    def test_failed_card_hides_traceback_behind_details(self):
        item = TestResult(
            nodeid="a.py::test_x",
            outcome="failed",
            concise_error="AssertionError: boom",
            longrepr="site-packages/_pytest/fixtures.py long traceback",
        )
        html = self._card(item)
        assert "<details" in html
        assert "site-packages/_pytest/fixtures.py" in html
        # The raw traceback must not appear outside the collapsed <details>.
        before_details = html.split("<details", 1)[0]
        assert "site-packages" not in before_details

    def test_skipped_card_shows_skip_badge_and_reason(self):
        item = TestResult(
            nodeid="a.py::test_x",
            outcome="skipped",
            skip_reason="high-concurrency localhost loads are flaky on macOS CI runners",
        )
        html = self._card(item)
        assert ">SKIP<" in html
        assert "high-concurrency localhost loads are flaky" in html

    def test_skipped_card_without_reason_shows_placeholder_not_silence(self):
        item = TestResult(nodeid="a.py::test_x", outcome="skipped", skip_reason=None)
        html = self._card(item)
        assert "No reason recorded." in html

    def test_whitespace_only_skip_reason_falls_back_to_placeholder(self):
        """Guards an older results.json written before the plugin normalised
        this: a truthy-but-blank reason would render as an empty line."""
        item = TestResult(nodeid="a.py::test_x", outcome="skipped", skip_reason="   ")
        html = self._card(item)
        assert "No reason recorded." in html

    def test_na_version_card_reads_distinctly_from_ordinary_skip(self):
        item = TestResult(nodeid="a.py::test_x", outcome="skipped", na_version=True)
        html = self._card(item)
        assert ">N/A<" in html
        assert "could not be determined" in html
        # Not the generic skip placeholder.
        assert "No reason recorded." not in html

    def test_na_version_card_keeps_the_recorded_version_gate_detail(self):
        """The plain-English lead must not swallow the actionable detail.

        _skip_version_unknown records which product and which min_version
        expression could not be evaluated; that is the only part of the card
        a reader can act on.
        """
        item = TestResult(
            nodeid="a.py::test_x",
            outcome="skipped",
            na_version=True,
            skip_reason=(
                "VIP: version unknown for workbench - cannot evaluate "
                "min_version(product='workbench', version='2026.01.0')"
            ),
        )
        html = self._card(item)
        assert "could not be determined" in html
        assert "min_version(product=&#x27;workbench&#x27;" in html
        assert "vip-skip-detail" in html

    def test_na_version_status_property(self):
        item = TestResult(nodeid="a.py::test_x", outcome="skipped", na_version=True)
        assert item.status == "na_version"

    def test_unknown_status_degrades_gracefully(self):
        style = report_html.outcome_style("weird")
        assert style.label == "?"


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
        assert report_html.dominant_feature_description(results) == "As a Posit Team admin"

    def test_no_descriptions_returns_none(self):
        results = [TestResult(nodeid="a", outcome="passed")]
        assert report_html.dominant_feature_description(results) is None

    def test_dominant_description_is_suppressed_on_card(self):
        item = TestResult(nodeid="a", outcome="passed", feature_description="As a Posit admin")
        html = report_html.description_html(item, dominant="As a Posit admin")
        assert html == ""

    def test_differing_description_is_shown(self):
        item = TestResult(nodeid="a", outcome="passed", feature_description="As a VIP user")
        html = report_html.description_html(item, dominant="As a Posit admin")
        assert "As a VIP user" in html

    def test_missing_description_renders_nothing(self):
        item = TestResult(nodeid="a", outcome="passed", feature_description=None)
        assert report_html.description_html(item, dominant="anything") == ""


# ---------------------------------------------------------------------------
# Marker badges (F8)
# ---------------------------------------------------------------------------


class TestMarkerBadges:
    def test_known_product_marker_gets_primary_badge(self):
        item = TestResult(nodeid="a", outcome="passed", markers=["connect"])
        html = report_html.product_badges_html(item)
        assert "badge-connect" in html
        assert "Connect" in html

    def test_cross_product_marker_gets_its_own_badge(self):
        item = TestResult(nodeid="a", outcome="passed", markers=["cross_product"])
        html = report_html.product_badges_html(item)
        assert "badge-cross-product" in html

    def test_performance_marker_with_no_product_still_gets_a_badge(self):
        # e.g. test_concurrency.feature scenarios carry only @performance.
        item = TestResult(nodeid="a", outcome="passed", markers=["performance"])
        html = report_html.product_badges_html(item)
        assert "badge-performance" in html

    def test_config_hygiene_marker_gets_a_badge(self):
        item = TestResult(nodeid="a", outcome="passed", markers=["config_hygiene"])
        assert "badge-config-hygiene" in report_html.product_badges_html(item)

    def test_ide_marker_gets_secondary_badge(self):
        item = TestResult(nodeid="a", outcome="passed", markers=["workbench", "rstudio"])
        html = report_html.product_badges_html(item)
        assert "badge-workbench" in html
        assert "badge-ide" in html
        assert "RStudio" in html

    def test_slow_marker_gets_secondary_badge(self):
        item = TestResult(nodeid="a", outcome="passed", markers=["workbench", "slow"])
        html = report_html.product_badges_html(item)
        assert "badge-slow" in html

    def test_structural_markers_render_nothing(self):
        item = TestResult(nodeid="a", outcome="passed", markers=["min_version", "if_applicable"])
        assert report_html.product_badges_html(item) == ""

    def test_multiple_product_markers_all_render(self):
        # e.g. test_publish_to_connect.feature: @workbench @connect @slow
        item = TestResult(nodeid="a", outcome="passed", markers=["workbench", "connect", "slow"])
        html = report_html.product_badges_html(item)
        assert "badge-workbench" in html
        assert "badge-connect" in html
        assert "badge-slow" in html


# ---------------------------------------------------------------------------
# category_for / group_by_category
# ---------------------------------------------------------------------------


class TestCategoryFor:
    """category_for prefers a scenario's own marker over the directory it
    lives in, falling back to TestResult.category (which derives the category
    from the nodeid path)."""

    def test_real_nodeid_shape_resolves_to_directory(self):
        item = TestResult(nodeid="src/vip_tests/connect/test_auth.py::test_login", outcome="passed")
        assert item.category == "connect"
        assert report_html.category_for(item) == "connect"

    def test_marker_match_takes_priority_over_path_scan(self):
        # A cross-cutting test physically under workbench/ but tagged @connect.
        item = TestResult(
            nodeid="src/vip_tests/workbench/test_publish.py::test_x",
            outcome="passed",
            markers=["connect"],
        )
        assert report_html.category_for(item) == "connect"

    def test_no_marker_and_no_known_path_segment_falls_back_to_category(self):
        item = TestResult(nodeid="tests/unknown/test_x.py::test_y", outcome="passed")
        assert report_html.category_for(item) == item.category

    def test_group_by_category_buckets_correctly(self):
        results = [
            TestResult(nodeid="src/vip_tests/connect/test_a.py::t1", outcome="passed"),
            TestResult(nodeid="src/vip_tests/workbench/test_b.py::t2", outcome="passed"),
            TestResult(nodeid="src/vip_tests/connect/test_c.py::t3", outcome="failed"),
        ]
        groups = report_html.group_by_category(results)
        assert len(groups["connect"]) == 2
        assert len(groups["workbench"]) == 1


# ---------------------------------------------------------------------------
# Per-product rollup (F7)
# ---------------------------------------------------------------------------


class TestRenderProductsTable:
    def test_no_products_configured(self):
        html = report_html.render_products_table(ReportData())
        assert "No products configured" in html

    def test_per_product_counts(self):
        data = ReportData(
            products=[
                ProductInfo(name="connect", configured=True, url="https://connect.example.com"),
            ],
            results=[
                TestResult(nodeid="src/vip_tests/connect/test_a.py::t1", outcome="passed"),
                TestResult(nodeid="src/vip_tests/connect/test_b.py::t2", outcome="failed"),
                TestResult(nodeid="src/vip_tests/connect/test_c.py::t3", outcome="skipped"),
            ],
        )
        html = report_html.render_products_table(data)
        assert "1 passed" in html
        assert "1 failed" in html
        assert "1 skipped" in html
        assert "3 tests" in html

    def test_a_scenario_tagged_for_two_products_counts_for_both(self):
        """The rollup rule is deliberately broader than category_for.

        A cross-product scenario exercised both products, so assigning it to a
        single bucket would silently under-count one of them. The product rows
        therefore do not sum to the run total; the Summary table is where the
        authoritative totals live.
        """
        item = TestResult(
            nodeid="src/vip_tests/cross_product/test_ssl.py::t1",
            outcome="passed",
            markers=["connect", "workbench"],
        )
        assert report_html.results_for_product([item], "connect") == [item]
        assert report_html.results_for_product([item], "workbench") == [item]

    def test_product_rollup_matches_on_directory_when_untagged(self):
        item = TestResult(
            nodeid="src/vip_tests/package_manager/test_repos.py::t1", outcome="passed"
        )
        assert report_html.results_for_product([item], "package_manager") == [item]
        assert report_html.results_for_product([item], "connect") == []

    def test_prerequisites_results_belong_to_no_product_row(self):
        item = TestResult(
            nodeid="src/vip_tests/prerequisites/test_components.py::t1",
            outcome="passed",
            markers=["prerequisites"],
        )
        assert report_html.results_for_product([item], "connect") == []
        assert report_html.results_for_product([item], "workbench") == []

    def test_configured_product_with_no_results_says_so(self):
        data = ReportData(products=[ProductInfo(name="workbench", configured=True)])
        html = report_html.render_products_table(data)
        assert "no results recorded" in html

    def test_unconfigured_product_is_excluded(self):
        data = ReportData(products=[ProductInfo(name="connect", configured=False)])
        html = report_html.render_products_table(data)
        assert "No products configured" in html


# ---------------------------------------------------------------------------
# Provenance (F9) — graceful with None fields
# ---------------------------------------------------------------------------


class TestRenderProvenanceTable:
    def test_all_none_renders_not_recorded(self):
        data = ReportData()  # exit_status defaults to 0; everything else None
        html = report_html.render_provenance_table(data)
        assert html.count("not recorded") == 5  # every field except exit_status
        assert "0 (OK" in html

    def test_populated_fields_render_values(self):
        data = ReportData(
            vip_version="2026.8.2",
            run_duration_seconds=3.448587332997704,
            python_version="3.12.2",
            platform="macOS-27.0-arm64-arm-64bit",
            basic_mode=False,
            exit_status=1,
        )
        html = report_html.render_provenance_table(data)
        assert "2026.8.2" in html
        assert "3.4s" in html
        assert "3.12.2" in html
        assert "macOS-27.0-arm64-arm-64bit" in html
        assert "full" in html
        assert "1 (tests were collected and run" in html

    def test_basic_mode_renders_basic(self):
        data = ReportData(basic_mode=True)
        html = report_html.render_provenance_table(data)
        assert "basic" in html

    def test_unrecognized_exit_status(self):
        data = ReportData(exit_status=99)
        html = report_html.render_provenance_table(data)
        assert "99 (unrecognized exit code)" in html


# ---------------------------------------------------------------------------
# Overall summary table
# ---------------------------------------------------------------------------


class TestRenderSummaryTable:
    def test_empty_results(self):
        html = report_html.render_summary_table(ReportData())
        assert "No results found" in html

    def test_all_passed_shows_pass_status(self):
        data = ReportData(results=[TestResult(nodeid="a", outcome="passed")])
        html = report_html.render_summary_table(data)
        assert "summary-status-pass" in html
        assert ">PASS<" in html

    def test_any_failure_shows_fail_status(self):
        data = ReportData(
            results=[
                TestResult(nodeid="a", outcome="passed"),
                TestResult(nodeid="b", outcome="failed"),
            ]
        )
        html = report_html.render_summary_table(data)
        assert "summary-status-fail" in html
        assert ">FAIL<" in html


# ---------------------------------------------------------------------------
# Page-level orchestration — empty/graceful inputs
# ---------------------------------------------------------------------------


class TestPageOrchestration:
    def test_render_details_page_empty_results(self):
        assert report_html.render_details_page(ReportData(), {}) == ""

    def test_render_actionable_cards_empty_results(self):
        assert report_html.render_actionable_cards(ReportData(), {}) == ""

    def test_render_actionable_cards_all_passed_says_so(self):
        data = ReportData(results=[TestResult(nodeid="a", outcome="passed")])
        html = report_html.render_actionable_cards(data, {})
        assert "No failures or skips" in html

    def test_render_actionable_cards_includes_failures_and_skips_only(self):
        data = ReportData(
            results=[
                TestResult(nodeid="a", outcome="passed", scenario_title="Passing one"),
                TestResult(nodeid="b", outcome="failed", scenario_title="Failing one"),
                TestResult(nodeid="c", outcome="skipped", scenario_title="Skipping one"),
            ]
        )
        html = report_html.render_actionable_cards(data, {})
        assert "Failing one" in html
        assert "Skipping one" in html
        assert "Passing one" not in html

    def test_render_actionable_cards_orders_failed_before_skipped(self):
        data = ReportData(
            results=[
                TestResult(nodeid="a", outcome="skipped", scenario_title="Skip"),
                TestResult(nodeid="b", outcome="failed", scenario_title="Fail"),
            ]
        )
        html = report_html.render_actionable_cards(data, {})
        assert html.index("Failed (1)") < html.index("Skipped (1)")

    def test_render_details_page_groups_by_category(self):
        data = ReportData(
            results=[
                TestResult(
                    nodeid="src/vip_tests/connect/test_a.py::t1",
                    outcome="passed",
                    scenario_title="Connect thing",
                ),
                TestResult(
                    nodeid="src/vip_tests/workbench/test_b.py::t2",
                    outcome="passed",
                    scenario_title="Workbench thing",
                ),
            ]
        )
        html = report_html.render_details_page(data, {})
        assert "Connect" in html
        assert "Workbench" in html
        assert html.index("Connect") < html.index("Workbench")  # sorted alphabetically

    def test_error_ids_are_unique_across_whole_details_page(self):
        data = ReportData(
            results=[
                TestResult(
                    nodeid="src/vip_tests/connect/test_a.py::t1",
                    outcome="failed",
                    longrepr="boom 1",
                ),
                TestResult(
                    nodeid="src/vip_tests/workbench/test_b.py::t2",
                    outcome="failed",
                    longrepr="boom 2",
                ),
            ]
        )
        html = report_html.render_details_page(data, {})
        assert 'id="vip-error-0"' in html
        assert 'id="vip-error-1"' in html

    def test_clipboard_script_included_once(self):
        data = ReportData(results=[TestResult(nodeid="a", outcome="failed", longrepr="boom")])
        html = report_html.render_details_page(data, {})
        assert html.count("navigator.clipboard.writeText") == 1

    def test_print_expand_script_included_once(self):
        """A printed report that omits its tracebacks is the failure mode here,
        so guard against the script being dropped from a page."""
        data = ReportData(results=[TestResult(nodeid="a", outcome="failed", longrepr="boom")])
        html = report_html.render_details_page(data, {})
        assert html.count("addEventListener('beforeprint'") == 1

    def test_print_expand_is_idempotent(self):
        """Chromium fires both beforeprint and the print matchMedia change, so
        expand() runs twice. Without the guard the second call resets the record
        and restore() re-collapses nothing, leaving the report permanently
        expanded after a print. The behaviour itself is JS and needs a browser;
        this only pins the guard so it cannot be dropped silently.
        """
        assert "if (expanded) return;" in report_html.PRINT_EXPAND_SCRIPT
        assert "if (!expanded) return;" in report_html.PRINT_EXPAND_SCRIPT


# ---------------------------------------------------------------------------
# Steps lookup (feature file resolution)
# ---------------------------------------------------------------------------


class TestFeatureStepIndex:
    def test_missing_feature_file_returns_empty_list(self):
        index = report_html.FeatureStepIndex()
        item = TestResult(nodeid="vip_tests/nope/test_missing.py::test_x", outcome="passed")
        assert index.steps_for(item) == []

    def test_no_scenario_title_returns_empty_list(self):
        index = report_html.FeatureStepIndex()
        item = TestResult(nodeid="a.py::test_x", outcome="passed", scenario_title=None)
        assert index.steps_for(item) == []

    def test_steps_html_empty_for_no_steps(self):
        assert report_html.steps_html([]) == ""

    def test_steps_html_renders_list(self):
        html = report_html.steps_html(["Given a thing", "Then another thing"])
        assert "Given a thing" in html
        assert "<details" in html
