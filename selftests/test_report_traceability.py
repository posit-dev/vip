"""The compliance traceability section, in both rendering backends.

The section exists because the report is the artifact a customer actually
receives. Before it, every field this feature added -- the matrix, the control
tags, the per-check timestamps -- lived only in results.json and `vip trace`
output, so a reader of the PDF saw none of it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from conftest import matrix_from_statuses
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
from vip.traceability import ControlSpec, build_traceability_matrix, matrix_from_env


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
        assert rows["Covered, executed and passing"] == "1"
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


class TestTraceabilityRenderFailure:
    """The failure branch renders customer-controlled text and must escape it.

    A ControlListError message embeds the VIP_CONTROLS path and control ids
    read straight out of a customer-authored controls.toml, and the report is
    published publicly. IPython.display.Markdown passes raw HTML through in
    Quarto, so the old Markdown rendering of this message was a live
    injection point.
    """

    HOSTILE = "<img src=x onerror=alert(1)> and <script>alert(2)</script>"

    def test_hostile_error_text_is_escaped(self):
        html = report_html.render_traceability_error(ValueError(self.HOSTILE))
        assert "<img" not in html
        assert "<script>" not in html
        assert "&lt;img src=x onerror=alert(1)&gt;" in html
        assert "&lt;script&gt;alert(2)&lt;/script&gt;" in html

    def test_the_failure_is_still_visible(self):
        html = report_html.render_traceability_error(ValueError("boom"))
        assert "Could not render the traceability section" in html
        assert "boom" in html

    def test_index_qmd_routes_the_failure_through_the_escaping_helper(self):
        """Drift guard on the cell itself, where the vulnerability lived.

        The helper cannot escape a value the .qmd never hands it, so assert
        the except branch calls it through HTML() and no longer formats the
        message into Markdown.
        """
        qmd = (Path(__file__).parent.parent / "report" / "index.qmd").read_text()
        assert "display(HTML(report_html.render_traceability_error(_trace_error)))" in qmd
        assert "TRACEABILITY_RENDER_FAILURE" not in qmd, (
            "the .qmd must not format the failure message itself; "
            "report_html.render_traceability_error owns the escaping"
        )


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


class TestCoverageBadge:
    def test_html_coverage_badge_uses_a_class_that_exists_in_styles_css(self):
        css = (Path(__file__).parent.parent / "report" / "styles.css").read_text()
        matrix = matrix_from_statuses(statuses={"c1": ["passed"]})
        html = report_html.render_traceability(matrix)
        for cls in ("vip-badge", "trace-caveat", "trace-warning"):
            assert f".{cls}" in css, (
                f"{cls} is referenced by the renderer but absent from styles.css"
            )
        assert "class='badge'" not in html


class TestRiskIsVisibleInBothEditions:
    """The customer's risk rating, rendered rather than left in the CSV export.

    `risk` reached `vip trace --format csv/json` from the day the control
    loader carried it, but neither report edition showed it -- and the report
    is what an auditor is handed. CSA is a risk-based framework, so a matrix
    with no risk column reads as a flat checklist.
    """

    @staticmethod
    def _matrix():
        data = ReportData(results=[_result("t.py::ok", "ok", title="Audit trail is written")])
        controls = {
            "ok": ControlSpec(
                "ok", "Audit trail recorded", reference="21 CFR 11.10(e)", risk="high"
            ),
            "unrated": ControlSpec("unrated", "No risk assigned"),
        }
        return build_traceability_matrix(data, controls)

    def test_control_row_carries_the_risk_verbatim(self):
        by_id = {r.control_id: r.risk for r in control_rows(self._matrix())}
        assert by_id["ok"] == "high"
        assert by_id["unrated"] == ""

    def test_html_edition_shows_the_risk(self):
        html = report_html.render_traceability(self._matrix())
        assert "risk: high" in html

    def test_typst_edition_shows_the_risk(self):
        typst = report_typst.render_traceability(self._matrix())
        assert "risk: high" in typst

    @pytest.mark.parametrize("backend", [report_html, report_typst])
    def test_an_unrated_control_renders_no_empty_risk_line(self, backend):
        """An absent rating must not become a dangling "risk: " subline."""
        rendered = backend.render_traceability(self._matrix())
        assert rendered.count("risk: ") == 1

    def test_a_risk_value_vip_does_not_recognize_is_still_rendered(self):
        """VIP carries the rating through uninterpreted; it does not rank it."""
        data = ReportData(results=[_result("t.py::ok", "ok")])
        controls = {"ok": ControlSpec("ok", "Some control", risk="Class II / banana")}
        matrix = build_traceability_matrix(data, controls)
        assert "Class II / banana" in report_html.render_traceability(matrix)
        assert "Class II / banana" in report_typst.render_traceability(matrix)


class TestMatrixFromEnv:
    """The entry point both Quarto cells call, where neither may raise.

    The cells used to hold this logic twice over, so the HTML and PDF
    editions could drift apart on the same inputs, and neither copy could be
    tested without rendering a whole document.
    """

    def _results(self, tmp_path, rows=()):
        data = json.dumps({"schema_version": "1.0", "results": list(rows)}, indent=2).encode()
        p = tmp_path / "results.json"
        p.write_bytes(data)
        p.with_name("results.json.sha256").write_text(
            f"{hashlib.sha256(data).hexdigest()}  results.json\n"
        )
        return p

    def _controls(self, tmp_path, body='[controls.ok]\ndescription = "d"\n'):
        p = tmp_path / "controls.toml"
        p.write_text(body, encoding="utf-8")
        return p

    def test_no_control_list_means_no_section(self, tmp_path):
        assert matrix_from_env(self._results(tmp_path), env={}) == (None, None)

    def test_a_control_list_builds_a_matrix(self, tmp_path):
        results = self._results(
            tmp_path,
            [{"nodeid": "t.py::ok", "outcome": "passed", "markers": ["control-ok"]}],
        )
        controls = self._controls(tmp_path)

        matrix, error = matrix_from_env(results, env={"VIP_CONTROLS": str(controls)})

        assert error is None
        assert [e.control.control_id for e in matrix.entries] == ["ok"]
        assert [m.nodeid for m in matrix.entries[0].matches] == ["t.py::ok"]

    def test_the_digest_describes_the_bytes_the_matrix_was_built_from(self, tmp_path):
        """One read, so the attestation and the matrix cannot disagree.

        Loading the results separately from hashing them left a window where
        the digest in the provenance block described a file the matrix had not
        been built from.
        """
        results = self._results(
            tmp_path,
            [{"nodeid": "t.py::ok", "outcome": "passed", "markers": ["control-ok"]}],
        )
        controls = self._controls(tmp_path)

        matrix, _ = matrix_from_env(results, env={"VIP_CONTROLS": str(controls)})

        assert (
            matrix.provenance["results_sha256"] == hashlib.sha256(results.read_bytes()).hexdigest()
        )
        assert matrix.provenance["results_sha256_sidecar_verified"] is True
        assert matrix.entries[0].matches

    def test_a_bad_control_list_returns_the_reason_instead_of_raising(self, tmp_path):
        results = self._results(tmp_path)
        controls = self._controls(tmp_path, "[controls.ok]\n")

        matrix, error = matrix_from_env(results, env={"VIP_CONTROLS": str(controls)})

        assert matrix is None
        assert "missing a description" in error

    def test_a_failed_checksum_returns_the_reason_instead_of_raising(self, tmp_path):
        results = self._results(tmp_path)
        results.with_name("results.json.sha256").write_text(f"{'0' * 64}  results.json\n")
        controls = self._controls(tmp_path)

        matrix, error = matrix_from_env(results, env={"VIP_CONTROLS": str(controls)})

        assert matrix is None
        assert "checksum mismatch" in error

    def test_a_missing_results_file_returns_the_reason_instead_of_raising(self, tmp_path):
        """A render must not die on a path that is not there."""
        controls = self._controls(tmp_path)

        matrix, error = matrix_from_env(
            tmp_path / "absent.json", env={"VIP_CONTROLS": str(controls)}
        )

        assert matrix is None
        assert error
