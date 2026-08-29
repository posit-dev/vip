import hashlib

from vip.reporting import ReportData, TestResult
from vip.traceability import ControlSpec, build_traceability_matrix, verify_results_checksum


def _result(nodeid, markers, outcome="passed", **kw):
    return TestResult(
        nodeid=nodeid,
        outcome=outcome,
        markers=markers,
        scenario_title=kw.pop("title", "A scenario"),
        started_at="2026-08-28T12:00:00+00:00",
        finished_at="2026-08-28T12:00:01+00:00",
        **kw,
    )


def _controls(**kw):
    return {
        cid: ControlSpec(control_id=cid, description=f"desc {cid}", **opts)
        for cid, opts in kw.items()
    }


def test_covered_control_lists_its_scenarios():
    data = ReportData(results=[_result("t.py::a", ["connect", "control-x"], title="Scenario A")])
    matrix = build_traceability_matrix(data, _controls(x={}))
    entry = matrix.entries[0]
    assert entry.coverage == "covered"
    assert entry.matches[0].scenario_title == "Scenario A"
    assert entry.matches[0].status == "passed"
    assert entry.matches[0].started_at == "2026-08-28T12:00:00+00:00"


def test_uncovered_automated_control_is_a_gap():
    matrix = build_traceability_matrix(ReportData(results=[]), _controls(x={}))
    assert matrix.entries[0].coverage == "gap"
    assert matrix.gap_count == 1


def test_procedural_control_is_not_a_gap():
    controls = _controls(x={"verification": "procedural"})
    matrix = build_traceability_matrix(ReportData(results=[]), controls)
    assert matrix.entries[0].coverage == "not_automatable"
    assert matrix.gap_count == 0


def test_one_control_satisfied_by_several_scenarios():
    data = ReportData(
        results=[
            _result("t.py::a", ["control-x"], title="A"),
            _result("t.py::b", ["control-x"], title="B"),
        ]
    )
    entry = build_traceability_matrix(data, _controls(x={})).entries[0]
    assert [m.scenario_title for m in entry.matches] == ["A", "B"]


def test_one_scenario_satisfies_several_controls():
    data = ReportData(results=[_result("t.py::a", ["control-x", "control-y"])])
    matrix = build_traceability_matrix(data, _controls(x={}, y={}))
    assert all(e.coverage == "covered" for e in matrix.entries)


def test_unrecognized_tag_is_reported():
    data = ReportData(results=[_result("t.py::a", ["control-typo"])])
    matrix = build_traceability_matrix(data, _controls(x={}))
    assert matrix.unrecognized_tags == ["control-typo"]


def test_failure_detail_is_carried():
    data = ReportData(
        results=[
            _result("t.py::a", ["control-x"], outcome="failed", concise_error="boom"),
        ]
    )
    match = build_traceability_matrix(data, _controls(x={})).entries[0].matches[0]
    assert match.status == "failed"
    assert match.detail == "boom"


def test_skip_reason_is_carried():
    data = ReportData(
        results=[
            _result("t.py::a", ["control-x"], outcome="skipped", skip_reason="not configured"),
        ]
    )
    assert build_traceability_matrix(data, _controls(x={})).entries[0].matches[0].detail == (
        "not configured"
    )


def test_na_version_status_is_distinct():
    data = ReportData(
        results=[_result("t.py::a", ["control-x"], outcome="skipped", na_version=True)]
    )
    assert build_traceability_matrix(data, _controls(x={})).entries[0].matches[0].status == (
        "na_version"
    )


def test_entries_and_matches_are_sorted_deterministically():
    data = ReportData(
        results=[
            _result("t.py::z", ["control-b"], title="Z"),
            _result("t.py::a", ["control-b"], title="A"),
        ]
    )
    matrix = build_traceability_matrix(data, _controls(b={}, a={}))
    assert [e.control.control_id for e in matrix.entries] == ["a", "b"]
    b_entry = next(e for e in matrix.entries if e.control.control_id == "b")
    assert [m.nodeid for m in b_entry.matches] == ["t.py::a", "t.py::z"]


def test_custom_tag_prefix():
    data = ReportData(results=[_result("t.py::a", ["req-x"])])
    matrix = build_traceability_matrix(data, _controls(x={}), tag_prefix="req-")
    assert matrix.entries[0].coverage == "covered"


def test_provenance_is_carried_from_the_report():
    data = ReportData(
        generated_at="2026-08-28T12:00:00+00:00",
        vip_version="2026.8.3",
        schema_version="1.0",
        basic_mode=True,
        execution={"hostname": "runner-1", "git": None, "ci": None},
    )
    prov = build_traceability_matrix(data, _controls(x={})).provenance
    assert prov["vip_version"] == "2026.8.3"
    assert prov["basic_mode"] is True
    assert prov["execution"]["hostname"] == "runner-1"
    assert prov["results_schema_version"] == "1.0"


def test_verify_results_checksum_reports_sidecar_presence(tmp_path):
    results = tmp_path / "results.json"
    data = b'{"results": []}'
    results.write_bytes(data)
    expected_digest = hashlib.sha256(data).hexdigest()
    results.with_name("results.json.sha256").write_text(f"{expected_digest}  results.json\n")

    digest, sidecar_present = verify_results_checksum(results)
    assert digest == expected_digest
    assert sidecar_present is True


def test_verify_results_checksum_reports_missing_sidecar(tmp_path):
    results = tmp_path / "results.json"
    data = b'{"results": []}'
    results.write_bytes(data)
    expected_digest = hashlib.sha256(data).hexdigest()

    digest, sidecar_present = verify_results_checksum(results)
    assert digest == expected_digest
    assert sidecar_present is False


def test_provenance_defaults_checksum_fields_to_none():
    # A matrix built directly from a ReportData -- as every test above does,
    # with no results file on disk -- must still work with no digest to carry.
    prov = build_traceability_matrix(ReportData(results=[]), _controls(x={})).provenance
    assert prov["results_sha256"] is None
    assert prov["results_sha256_sidecar_verified"] is None


def test_provenance_carries_results_sha256_when_supplied():
    prov = build_traceability_matrix(
        ReportData(results=[]),
        _controls(x={}),
        results_sha256="deadbeef",
        results_sha256_sidecar_verified=True,
    ).provenance
    assert prov["results_sha256"] == "deadbeef"
    assert prov["results_sha256_sidecar_verified"] is True


def test_provenance_distinguishes_sidecar_absent_from_verified():
    verified = build_traceability_matrix(
        ReportData(results=[]),
        _controls(x={}),
        results_sha256="deadbeef",
        results_sha256_sidecar_verified=True,
    ).provenance
    absent = build_traceability_matrix(
        ReportData(results=[]),
        _controls(x={}),
        results_sha256="deadbeef",
        results_sha256_sidecar_verified=None,
    ).provenance
    assert verified["results_sha256_sidecar_verified"] is True
    assert absent["results_sha256_sidecar_verified"] is None
    assert verified["results_sha256_sidecar_verified"] != absent["results_sha256_sidecar_verified"]
