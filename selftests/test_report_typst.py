"""Tests for vip.report_typst — the Typst (PDF) backend of the VIP report.

The property that matters most is the same one test_report_html.py guards for
HTML: injection. Test titles, error text, and hints flow into the document
verbatim, and in Typst an unescaped `#` calls a function, `*`/`_` toggle
styling, and `$` opens math. Every dynamic value must therefore arrive inside
a double-quoted Typst string literal with `"` and `\\` escaped.

Compilation is not covered here: selftests run without Quarto/Typst in CI, so
these tests assert on the generated markup. The example-report workflow
compiles the real document end to end.
"""

from __future__ import annotations

from conftest import matrix_from_statuses
from vip import report_typst
from vip.report_content import NA_VERSION_EXPLANATION
from vip.reporting import ReportData, TestResult

# Typst metacharacters that must never reach the document outside a string
# literal: function call, strong, emphasis, math, label/ref, code block.
HOSTILE = '#panic("owned") $x^2$ *bold* _under_ @ref [bracket] \\slash "quoted"'


def _card(item: TestResult, hints: dict | None = None) -> str:
    return report_typst.render_card(
        item,
        feature_index=report_typst.FeatureStepIndex(),
        hints=hints or {},
        dominant_description=None,
    )


class TestLit:
    def test_plain_string_is_quoted(self):
        assert report_typst._lit("hello") == '"hello"'

    def test_quotes_and_backslashes_are_escaped(self):
        assert report_typst._lit('say "hi" \\ bye') == '"say \\"hi\\" \\\\ bye"'

    def test_backslash_escaped_before_quote(self):
        # A pre-escaped quote in the input must not collapse into a live one.
        assert report_typst._lit('\\"') == '"\\\\\\""'

    def test_newlines_become_typst_escapes(self):
        assert report_typst._lit("a\nb") == '"a\\nb"'

    def test_carriage_returns_are_dropped_and_tabs_widened(self):
        assert report_typst._lit("a\r\n\tb") == '"a\\n    b"'

    def test_typst_markup_survives_only_as_text(self):
        lit = report_typst._lit(HOSTILE)
        # The dangerous characters are present — inside the literal — and the
        # only unescaped double quotes are the delimiters.
        assert lit.startswith('"') and lit.endswith('"')
        assert lit.count('"') - lit.count('\\"') == 2


class TestEscaping:
    """Hostile report content must land inside string literals only."""

    def test_hostile_title_is_a_string_literal(self):
        item = TestResult(nodeid="a.py::t", outcome="passed", scenario_title=HOSTILE)
        markup = _card(item)
        assert '\\"owned\\"' in markup
        assert '#panic("owned")' not in markup

    def test_hostile_traceback_is_a_string_literal(self):
        item = TestResult(
            nodeid="a.py::t",
            outcome="failed",
            concise_error=HOSTILE,
            longrepr='#set page(fill: red)\n#panic("boom")',
        )
        markup = _card(item)
        # The traceback arrives as one literal with escaped quotes, so the
        # live-markup form (unescaped quotes after #panic) never appears.
        assert '#panic("boom")' not in markup
        assert '#set page(fill: red)\\n#panic(\\"boom\\")' in markup

    def test_hostile_hint_entries_are_string_literals(self):
        item = TestResult(nodeid="a.py::t", outcome="failed", scenario_title="s")
        hints = {"s": {"likely_causes": [HOSTILE], "suggested_steps": ["#panic(1)"]}}
        markup = _card(item, hints)
        # As a bare token it would run; inside quotes it is inert text.
        assert '"#panic(1)"' in markup
        assert markup.count("#panic(1)") == markup.count('"#panic(1)"')

    def test_docs_url_is_a_string_literal_in_link(self):
        item = TestResult(nodeid="a.py::t", outcome="failed", scenario_title="s")
        hints = {"s": {"docs_url": 'https://x.example/#frag"quote'}}
        markup = _card(item, hints)
        assert 'link("https://x.example/#frag\\"quote")' in markup


class TestWrap:
    def test_short_lines_untouched(self):
        assert report_typst._wrap("short line", 40) == "short line"

    def test_wraps_at_spaces_not_mid_word(self):
        wrapped = report_typst._wrap("alpha beta gamma delta", 12)
        lines = wrapped.split("\n")
        assert all(len(line) <= 12 for line in lines)
        # Every word survives whole on some line.
        rejoined = " ".join(part for line in lines for part in line.split())
        assert rejoined == "alpha beta gamma delta"

    def test_single_long_token_splits_as_last_resort(self):
        token = "x" * 100
        wrapped = report_typst._wrap(token, 40)
        assert all(len(line) <= 40 for line in wrapped.split("\n"))
        assert wrapped.replace("\n", "").replace(" ", "") == token

    def test_continuation_keeps_indent(self):
        line = ("    " + "word " * 20).rstrip()
        continuation = report_typst._wrap(line, 30).split("\n")[1]
        assert continuation.startswith("        ")

    def test_line_structure_preserved(self):
        text = "one\ntwo\nthree"
        assert report_typst._wrap(text, 80) == text


class TestCardContent:
    def test_failed_card_carries_chip_error_and_traceback(self):
        item = TestResult(
            nodeid="a.py::t",
            outcome="failed",
            scenario_title="Connect is reachable",
            concise_error="AssertionError: expected 200",
            longrepr="Traceback...",
        )
        markup = _card(item)
        assert '"FAIL"' in markup
        assert '"Connect is reachable"' in markup
        assert '"AssertionError: expected 200"' in markup
        assert '"Traceback..."' in markup

    def test_passed_card_has_no_error_block(self):
        item = TestResult(nodeid="a.py::t", outcome="passed", longrepr="stale")
        assert "stale" not in _card(item)

    def test_na_version_card_explains_itself(self):
        item = TestResult(
            nodeid="a.py::t", outcome="skipped", na_version=True, skip_reason="v unknown"
        )
        markup = _card(item)
        assert report_typst._lit(NA_VERSION_EXPLANATION) in markup
        assert '"v unknown"' in markup

    def test_product_markers_become_pills(self):
        item = TestResult(nodeid="a.py::t", outcome="passed", markers=["connect", "slow"])
        markup = _card(item)
        assert 'vip-pill("Connect", "#447099")' in markup
        assert 'vip-tag("Slow")' in markup


class TestDocument:
    def test_empty_results_render_the_placeholder(self):
        markup = report_typst.render_document(ReportData(), {})
        assert "No results found" in markup
        assert markup.startswith(report_typst.PREAMBLE)

    def test_empty_results_still_carry_the_matrix_when_one_was_asked_for(self):
        """index.qmd renders the section at zero results, so the PDF must too.

        Returning early on an empty results file dropped the section from the
        PDF alone, splitting the two editions on exactly the run a reader is
        most likely to misread -- one where every automated control is a gap.
        """
        from vip.traceability import ControlSpec, build_traceability_matrix

        matrix = build_traceability_matrix(
            ReportData(), {"audit-trail": ControlSpec("audit-trail", "An audit trail exists")}
        )
        markup = report_typst.render_document(ReportData(), {}, matrix)
        assert "No results found" in markup
        assert report_typst._lit("Compliance Traceability") in markup
        assert report_typst._lit("audit-trail") in markup

    def test_empty_results_without_a_matrix_are_unchanged(self):
        assert report_typst.render_document(ReportData(), {}, None) == (
            report_typst.render_document(ReportData(), {})
        )

    def test_document_carries_every_section(self):
        data = ReportData(
            deployment_name="Acme",
            results=[
                TestResult(nodeid="src/vip_tests/connect/a.py::t1", outcome="failed"),
                TestResult(nodeid="src/vip_tests/connect/a.py::t2", outcome="passed"),
            ],
        )
        markup = report_typst.render_document(data, {})
        for section in (
            "VIP Validation Report",
            "Products Under Test",
            "Summary",
            "Provenance",
            "Failures & Skips",
            "Detailed Results",
        ):
            assert report_typst._lit(section) in markup
        assert "#pagebreak()" in markup

    def test_all_passed_run_says_so_in_failures_section(self):
        data = ReportData(results=[TestResult(nodeid="a.py::t", outcome="passed")])
        markup = report_typst.render_document(data, {})
        assert "No failures or skips" in markup

    def test_not_recorded_provenance_renders_placeholder(self):
        data = ReportData(results=[TestResult(nodeid="a.py::t", outcome="passed")])
        markup = report_typst.render_document(data, {})
        assert '"not recorded"' in markup


class TestCoverageBadge:
    def test_coverage_badge_uses_the_same_chip_as_an_outcome(self):
        """vip-pill is a saturated fill with white text; the HTML edition is a chip."""
        matrix = matrix_from_statuses(statuses={"c1": ["passed"]})
        out = report_typst.render_traceability(matrix)
        assert "vip-chip" in out
        assert "vip-pill" not in out
