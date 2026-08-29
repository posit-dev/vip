"""The compliance traceability section, in both rendering backends.

The section exists because the report is the artifact a customer actually
receives. Before it, every field this feature added -- the matrix, the control
tags, the per-check timestamps -- lived only in results.json and `vip trace`
output, so a reader of the PDF saw none of it.
"""

from __future__ import annotations

import pytest

from vip import report_html, report_typst
from vip.report_content import (
    COVERAGE_LABELS,
    COVERAGE_STYLE_KEY,
    control_rows,
    display_coverage,
    traceability_summary_rows,
    traceability_warnings,
)
from vip.reporting import ReportData, TestResult
from vip.traceability import ControlSpec, build_traceability_matrix


def _result(nodeid, control, outcome="passed", title="S", **kw):
    return TestResult(
        nodeid=nodeid,
        outcome=outcome,
        markers=["connect", f"control-{control}"],
        scenario_title=title,
        started_at="2026-08-29T10:00:00+00:00",
        **kw,
    )


def _matrix():
    """One control of every coverage state the section can show."""
    data = ReportData(
        results=[
            _result("t.py::ok", "ok", title="Audit trail is written"),
            _result("t.py::sk", "skipped-only", outcome="skipped", skip_reason="not configured"),
            _result("t.py::bad", "failing", outcome="failed", title="Privileged action"),
        ]
    )
    controls = {
        "ok": ControlSpec("ok", "Audit trail recorded", reference="21 CFR 11.10(e)"),
        "skipped-only": ControlSpec("skipped-only", "Privileged action refused"),
        "failing": ControlSpec("failing", "Records cannot be deleted"),
        "missing": ControlSpec("missing", "Nothing tests this"),
        "manual": ControlSpec("manual", "Training records", verification="procedural"),
    }
    return build_traceability_matrix(data, controls)


class TestCoverageDisplay:
    def test_all_five_states_are_distinguishable(self):
        by_id = {r.control_id: r.coverage for r in control_rows(_matrix())}
        assert by_id["ok"] == "covered"
        assert by_id["failing"] == "covered_failed"
        assert by_id["skipped-only"] == "covered_not_executed"
        assert by_id["missing"] == "gap"
        assert by_id["manual"] == "not_automatable"

    def test_a_failed_scenario_displays_as_covered_failed(self):
        """Coverage folds in outcome: a failing scenario is not evidence."""
        row = next(r for r in control_rows(_matrix()) if r.control_id == "failing")
        assert row.coverage == "covered_failed"
        assert row.scenarios[0][1] == "failed"

    def test_every_coverage_value_has_a_label_and_a_style(self):
        for value in COVERAGE_LABELS:
            assert value in COVERAGE_STYLE_KEY

    def test_display_coverage_leaves_a_gap_alone(self):
        entry = next(e for e in _matrix().entries if e.control.control_id == "missing")
        assert display_coverage(entry) == "gap"

    def test_summary_counts_split_executed_from_covered(self):
        rows = dict(traceability_summary_rows(_matrix()))
        assert rows["Controls"] == "5"
        assert rows["Covered and executed"] == "1"
        assert rows["Covered, not executed"] == "1"
        assert rows["Covered, failing"] == "1"
        assert rows["Gaps"] == "1"
        assert rows["Not automatable"] == "1"

    def test_warning_names_the_unexecuted_control(self):
        assert any("skipped-only" in w for w in traceability_warnings(_matrix()))

    def test_no_warning_when_everything_ran(self):
        data = ReportData(results=[_result("t.py::ok", "ok")])
        matrix = build_traceability_matrix(data, {"ok": ControlSpec("ok", "d")})
        assert traceability_warnings(matrix) == []


class TestHtmlBackend:
    def test_renders_every_state_and_the_caveat(self):
        html = report_html.render_traceability(_matrix())
        for label in ("COVERED", "NOT RUN", "GAP", "N/A (manual)"):
            assert label in html
        assert "not an attestation" in html
        assert "21 CFR 11.10(e)" in html

    def test_a_gap_says_so_rather_than_rendering_empty(self):
        assert "no tagged scenario" in report_html.render_traceability(_matrix())

    def test_customer_supplied_text_is_escaped(self):
        data = ReportData(results=[])
        matrix = build_traceability_matrix(
            data, {"x": ControlSpec("x", "<script>alert(1)</script> & co")}
        )
        html = report_html.render_traceability(matrix)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestTypstBackend:
    def test_renders_every_state(self):
        typ = report_typst.render_traceability(_matrix())
        for label in ("COVERED", "NOT RUN", "GAP", "N/A (manual)"):
            assert label in typ

    @pytest.mark.parametrize("hostile", ["#heading[x]", "*bold*", "$x^2$", 'quote " and \\ slash'])
    def test_customer_text_cannot_inject_typst(self, hostile):
        """A control list is authored outside VIP, so its text is untrusted."""
        matrix = build_traceability_matrix(ReportData(results=[]), {"x": ControlSpec("x", hostile)})
        typ = report_typst.render_traceability(matrix)
        escaped = hostile.replace("\\", "\\\\").replace('"', '\\"')
        assert f'"{escaped}"' in typ

    def test_a_multi_line_cell_is_one_expression(self):
        """A table cell must be a single expression; text(..)#block(..) is not."""
        typ = report_typst.render_traceability(_matrix())
        assert ")#block(" not in typ

    def test_document_without_a_matrix_omits_the_section(self):
        """The default path must be byte-identical to before the section existed."""
        data = ReportData(results=[_result("t.py::ok", "ok")])
        assert "Compliance Traceability" not in report_typst.render_document(data, {})

    def test_document_with_a_matrix_includes_the_section(self):
        data = ReportData(results=[_result("t.py::ok", "ok")])
        doc = report_typst.render_document(data, {}, _matrix())
        assert "Compliance Traceability" in doc
        assert "NOT RUN" in doc
