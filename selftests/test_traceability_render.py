import csv
import io
import json

from vip.reporting import ReportData, TestResult
from vip.traceability import (
    ControlSpec,
    build_traceability_matrix,
    render_csv,
    render_json,
)

CSV_COLUMNS = [
    "control_id",
    "description",
    "reference",
    "risk",
    "verification",
    "responsibility",
    "coverage",
    "scenario",
    "nodeid",
    "status",
    "started_at",
    "finished_at",
    "detail",
    "notes",
]


def _matrix():
    data = ReportData(
        generated_at="2026-08-28T12:00:00+00:00",
        vip_version="2026.8.3",
        results=[
            TestResult(
                nodeid="t.py::a",
                outcome="passed",
                markers=["control-x"],
                scenario_title="Scenario A",
                started_at="2026-08-28T12:00:00+00:00",
                finished_at="2026-08-28T12:00:01+00:00",
            )
        ],
    )
    controls = {
        "x": ControlSpec("x", "Audit trail", reference="21 CFR 11.10(e)", risk="high"),
        "y": ControlSpec("y", "Training records", verification="procedural"),
    }
    return build_traceability_matrix(data, controls)


def test_csv_has_the_expected_header():
    reader = csv.reader(io.StringIO(render_csv(_matrix())))
    assert next(reader) == CSV_COLUMNS


def test_csv_emits_one_row_per_match_and_one_for_a_gap():
    rows = list(csv.DictReader(io.StringIO(render_csv(_matrix()))))
    assert len(rows) == 2
    covered = next(r for r in rows if r["control_id"] == "x")
    assert covered["scenario"] == "Scenario A"
    assert covered["status"] == "passed"
    assert covered["coverage"] == "covered"

    procedural = next(r for r in rows if r["control_id"] == "y")
    assert procedural["coverage"] == "not_automatable"
    assert procedural["scenario"] == ""
    assert procedural["nodeid"] == ""


def test_csv_is_byte_identical_across_invocations():
    m = _matrix()
    assert render_csv(m) == render_csv(m)
    assert render_csv(_matrix()) == render_csv(_matrix())


def test_json_carries_provenance_and_schema_version():
    payload = json.loads(render_json(_matrix()))
    assert payload["schema_version"] == "1.0"
    assert payload["provenance"]["vip_version"] == "2026.8.3"
    assert payload["summary"]["gaps"] == 0
    assert payload["summary"]["covered"] == 1
    assert payload["summary"]["not_automatable"] == 1


def test_json_is_byte_identical_across_invocations():
    assert render_json(_matrix()) == render_json(_matrix())


def test_json_round_trips():
    payload = json.loads(render_json(_matrix()))
    entry = next(e for e in payload["controls"] if e["control_id"] == "x")
    assert entry["matches"][0]["nodeid"] == "t.py::a"
    assert entry["reference"] == "21 CFR 11.10(e)"


def test_csv_formula_injection_equals_sign():
    data = ReportData(
        generated_at="2026-08-28T12:00:00+00:00",
        vip_version="2026.8.3",
        results=[],
    )
    controls = {
        "a": ControlSpec("a", "=SUM(A1:A10)", verification="automated"),
    }
    matrix = build_traceability_matrix(data, controls)
    rows = list(csv.DictReader(io.StringIO(render_csv(matrix))))
    assert rows[0]["description"] == "'=SUM(A1:A10)"


def test_csv_formula_injection_plus_sign():
    data = ReportData(
        generated_at="2026-08-28T12:00:00+00:00",
        vip_version="2026.8.3",
        results=[],
    )
    controls = {
        "a": ControlSpec("a", "+1+1", verification="automated"),
    }
    matrix = build_traceability_matrix(data, controls)
    rows = list(csv.DictReader(io.StringIO(render_csv(matrix))))
    assert rows[0]["description"] == "'+1+1"


def test_csv_formula_injection_minus_sign():
    data = ReportData(
        generated_at="2026-08-28T12:00:00+00:00",
        vip_version="2026.8.3",
        results=[],
    )
    controls = {
        "a": ControlSpec("a", "-2+3", verification="automated"),
    }
    matrix = build_traceability_matrix(data, controls)
    rows = list(csv.DictReader(io.StringIO(render_csv(matrix))))
    assert rows[0]["description"] == "'-2+3"


def test_csv_formula_injection_at_sign():
    data = ReportData(
        generated_at="2026-08-28T12:00:00+00:00",
        vip_version="2026.8.3",
        results=[],
    )
    controls = {
        "a": ControlSpec("a", "@SUM(1,2)", verification="automated"),
    }
    matrix = build_traceability_matrix(data, controls)
    rows = list(csv.DictReader(io.StringIO(render_csv(matrix))))
    assert rows[0]["description"] == "'@SUM(1,2)"


def test_csv_formula_injection_leading_tab():
    data = ReportData(
        generated_at="2026-08-28T12:00:00+00:00",
        vip_version="2026.8.3",
        results=[],
    )
    controls = {
        "a": ControlSpec("a", "\t=SUM(1,2)", verification="automated"),
    }
    matrix = build_traceability_matrix(data, controls)
    rows = list(csv.DictReader(io.StringIO(render_csv(matrix))))
    assert rows[0]["description"] == "'\t=SUM(1,2)"


def test_csv_formula_injection_leading_carriage_return():
    data = ReportData(
        generated_at="2026-08-28T12:00:00+00:00",
        vip_version="2026.8.3",
        results=[],
    )
    controls = {
        "a": ControlSpec("a", "\r=SUM(1,2)", verification="automated"),
    }
    matrix = build_traceability_matrix(data, controls)
    rows = list(csv.DictReader(io.StringIO(render_csv(matrix))))
    assert rows[0]["description"] == "'\r=SUM(1,2)"


def test_csv_formula_injection_leading_newline():
    data = ReportData(
        generated_at="2026-08-28T12:00:00+00:00",
        vip_version="2026.8.3",
        results=[],
    )
    controls = {
        "a": ControlSpec("a", "\n=SUM(1,2)", verification="automated"),
    }
    matrix = build_traceability_matrix(data, controls)
    rows = list(csv.DictReader(io.StringIO(render_csv(matrix))))
    assert rows[0]["description"] == "'\n=SUM(1,2)"


def test_csv_normal_description_not_escaped():
    data = ReportData(
        generated_at="2026-08-28T12:00:00+00:00",
        vip_version="2026.8.3",
        results=[],
    )
    controls = {
        "a": ControlSpec("a", "Normal Description", verification="automated"),
    }
    matrix = build_traceability_matrix(data, controls)
    rows = list(csv.DictReader(io.StringIO(render_csv(matrix))))
    assert rows[0]["description"] == "Normal Description"
    assert not rows[0]["description"].startswith("'")


def test_json_non_ascii_appears_literally():
    data = ReportData(
        generated_at="2026-08-28T12:00:00+00:00",
        vip_version="2026.8.3",
        results=[],
    )
    controls = {
        "a": ControlSpec("a", "Café français", verification="automated"),
    }
    matrix = build_traceability_matrix(data, controls)
    rendered = render_json(matrix)
    assert "Café français" in rendered
    assert "\\u" not in rendered
