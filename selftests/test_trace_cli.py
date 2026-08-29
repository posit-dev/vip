import csv
import hashlib
import io
import json
import subprocess
import sys

import pytest

CONTROLS = """
[controls.x]
description = "Audit trail"
reference = "21 CFR 11.10(e)"

[controls.y]
description = "Training records"
verification = "procedural"
"""


def _results(tmp_path, schema_version="1.0", write_sidecar=True):
    payload = {
        "schema_version": schema_version,
        "generated_at": "2026-08-28T12:00:00+00:00",
        "vip_version": "2026.8.3",
        "results": [
            {
                "nodeid": "t.py::a",
                "outcome": "passed",
                "markers": ["connect", "control-x"],
                "scenario_title": "Scenario A",
                "started_at": "2026-08-28T12:00:00+00:00",
                "finished_at": "2026-08-28T12:00:01+00:00",
            }
        ],
    }
    if schema_version is None:
        payload.pop("schema_version")
    p = tmp_path / "results.json"
    data = json.dumps(payload, indent=2).encode()
    p.write_bytes(data)
    if write_sidecar:
        p.with_name("results.json.sha256").write_text(
            f"{hashlib.sha256(data).hexdigest()}  results.json\n"
        )
    controls = tmp_path / "controls.toml"
    controls.write_text(CONTROLS)
    return p, controls


def _run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "vip.cli", "trace", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def test_csv_to_stdout(tmp_path):
    results, controls = _results(tmp_path)
    proc = _run("--results", str(results), "--controls", str(controls))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("control_id,description,")
    assert "Scenario A" in proc.stdout


def test_json_format(tmp_path):
    results, controls = _results(tmp_path)
    proc = _run("--results", str(results), "--controls", str(controls), "--format", "json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["summary"]["covered"] == 1
    assert payload["summary"]["not_automatable"] == 1


def test_output_to_file(tmp_path):
    results, controls = _results(tmp_path)
    out = tmp_path / "matrix.csv"
    proc = _run("--results", str(results), "--controls", str(controls), "--output", str(out))
    assert proc.returncode == 0, proc.stderr
    assert out.read_text().startswith("control_id,")


def test_tampered_results_file_is_rejected(tmp_path):
    results, controls = _results(tmp_path)
    results.write_text(results.read_text().replace("passed", "failed"))
    proc = _run("--results", str(results), "--controls", str(controls))
    assert proc.returncode != 0
    assert "checksum" in proc.stderr.lower()


def test_missing_sidecar_is_allowed(tmp_path):
    results, controls = _results(tmp_path, write_sidecar=False)
    assert _run("--results", str(results), "--controls", str(controls)).returncode == 0


def test_provenance_carries_results_sha256_with_sidecar(tmp_path):
    results, controls = _results(tmp_path, write_sidecar=True)
    proc = _run("--results", str(results), "--controls", str(controls), "--format", "json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    expected_digest = hashlib.sha256(results.read_bytes()).hexdigest()
    assert payload["provenance"]["results_sha256"] == expected_digest
    assert payload["provenance"]["results_sha256_sidecar_verified"] is True


def test_provenance_carries_results_sha256_without_sidecar(tmp_path):
    results, controls = _results(tmp_path, write_sidecar=False)
    proc = _run("--results", str(results), "--controls", str(controls), "--format", "json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    expected_digest = hashlib.sha256(results.read_bytes()).hexdigest()
    assert payload["provenance"]["results_sha256"] == expected_digest
    assert payload["provenance"]["results_sha256_sidecar_verified"] is None


def test_pre_1_0_results_are_accepted(tmp_path):
    results, controls = _results(tmp_path, schema_version=None)
    assert _run("--results", str(results), "--controls", str(controls)).returncode == 0


def test_unknown_major_schema_is_rejected(tmp_path):
    results, controls = _results(tmp_path, schema_version="2.0")
    proc = _run("--results", str(results), "--controls", str(controls))
    assert proc.returncode != 0
    assert "2.0" in proc.stderr


def test_unknown_minor_schema_is_accepted(tmp_path):
    results, controls = _results(tmp_path, schema_version="1.7")
    assert _run("--results", str(results), "--controls", str(controls)).returncode == 0


def test_unrecognized_tag_warns_without_failing(tmp_path):
    results, controls = _results(tmp_path)
    payload = json.loads(results.read_text())
    payload["results"][0]["markers"].append("control-typo")
    data = json.dumps(payload, indent=2).encode()
    results.write_bytes(data)
    results.with_name("results.json.sha256").write_text(
        f"{hashlib.sha256(data).hexdigest()}  results.json\n"
    )
    proc = _run("--results", str(results), "--controls", str(controls))
    assert proc.returncode == 0
    assert "control-typo" in proc.stderr


def test_missing_control_file_errors_clearly(tmp_path):
    results, _ = _results(tmp_path)
    proc = _run("--results", str(results), "--controls", str(tmp_path / "nope.toml"))
    assert proc.returncode != 0
    assert "not found" in proc.stderr


def _raw_results(tmp_path, payload, write_sidecar=True):
    p = tmp_path / "results.json"
    data = json.dumps(payload, indent=2).encode()
    p.write_bytes(data)
    if write_sidecar:
        p.with_name("results.json.sha256").write_text(
            f"{hashlib.sha256(data).hexdigest()}  results.json\n"
        )
    controls = tmp_path / "controls.toml"
    controls.write_text(CONTROLS)
    return p, controls


def test_unknown_major_schema_with_malformed_results_errors_cleanly_before_load(tmp_path):
    # The schema gate must run BEFORE load_results ever indexes into the
    # results list, so a genuinely incompatible major (empty-dict results,
    # not just a future version number over current-shape rows) is refused
    # cleanly instead of crashing with a KeyError inside load_results.
    results, controls = _raw_results(
        tmp_path, {"schema_version": "2.0", "results": [{}]}, write_sidecar=False
    )
    proc = _run("--results", str(results), "--controls", str(controls))
    assert proc.returncode != 0
    assert "Error:" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_current_major_with_structurally_malformed_results_errors_cleanly(tmp_path):
    # No schema_version mismatch here -- this is a current-major file whose
    # results are the wrong shape, which must not escape as a raw KeyError.
    results, controls = _raw_results(tmp_path, {"results": [{}]}, write_sidecar=False)
    proc = _run("--results", str(results), "--controls", str(controls))
    assert proc.returncode != 0
    assert "Error:" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_malformed_json_without_sidecar_errors_cleanly(tmp_path):
    # No sidecar, so verify_results_checksum can't catch this as a checksum
    # mismatch -- this is exactly the population "missing sidecar is fine"
    # exists to serve (older results files), so it must not fall through to
    # a raw traceback.
    _, controls = _results(tmp_path, write_sidecar=False)
    results = tmp_path / "results.json"
    results.write_text("{not valid json")
    proc = _run("--results", str(results), "--controls", str(controls))
    assert proc.returncode != 0
    assert "Error" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_valid_json_non_object_without_sidecar_errors_cleanly(tmp_path):
    _, controls = _results(tmp_path, write_sidecar=False)
    results = tmp_path / "results.json"
    results.write_text("[]")
    proc = _run("--results", str(results), "--controls", str(controls))
    assert proc.returncode != 0
    assert "Error" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_unknown_major_schema_does_not_print_raw_warning(tmp_path):
    results, controls = _results(tmp_path, schema_version="2.0")
    proc = _run("--results", str(results), "--controls", str(controls))
    assert proc.returncode != 0
    assert "Error:" in proc.stderr
    assert "UserWarning" not in proc.stderr


def _write_controls(tmp_path, text):
    c = tmp_path / "c.toml"
    c.write_text(text, encoding="utf-8")
    return c


def _run_trace(results, controls, *extra):
    return _run("--results", str(results), "--controls", str(controls), *extra)


def _skipped_results(tmp_path, outcome="skipped"):
    p = tmp_path / "results.json"
    p.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "results": [
                    {
                        "nodeid": "t.py::a",
                        "outcome": outcome,
                        "markers": ["connect", "control-x"],
                        "skip_reason": "Connect is not configured",
                        "scenario_title": "S",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return p


class TestCoveredButNotExecuted:
    """A green matrix from a run that verified nothing must say so."""

    def test_skipped_only_control_warns_on_stderr(self, tmp_path):
        results = _skipped_results(tmp_path)
        controls = _write_controls(tmp_path, '[controls.x]\ndescription = "d"\n')
        r = _run_trace(results, controls)
        assert r.returncode == 0
        assert "no scenario that ran" in r.stderr
        assert "control-x" in r.stderr or "x" in r.stderr

    def test_json_summary_separates_executed_from_covered(self, tmp_path):
        results = _skipped_results(tmp_path)
        controls = _write_controls(tmp_path, '[controls.x]\ndescription = "d"\n')
        payload = json.loads(_run_trace(results, controls, "--format", "json").stdout)
        assert payload["summary"]["covered"] == 1
        assert payload["summary"]["gaps"] == 0
        assert payload["summary"]["covered_and_executed"] == 0
        assert payload["summary"]["covered_not_executed"] == 1
        assert payload["covered_without_execution"] == ["x"]

    def test_na_version_counts_as_not_executed(self, tmp_path):
        results = _skipped_results(tmp_path, outcome="skipped")
        raw = json.loads(results.read_text())
        raw["results"][0]["na_version"] = True
        results.write_text(json.dumps(raw), encoding="utf-8")
        controls = _write_controls(tmp_path, '[controls.x]\ndescription = "d"\n')
        payload = json.loads(_run_trace(results, controls, "--format", "json").stdout)
        assert payload["summary"]["covered_not_executed"] == 1

    def test_an_executed_control_does_not_warn(self, tmp_path):
        results = _skipped_results(tmp_path, outcome="passed")
        controls = _write_controls(tmp_path, '[controls.x]\ndescription = "d"\n')
        r = _run_trace(results, controls)
        assert "no scenario that ran" not in r.stderr


class TestOutputFormatResolution:
    def test_json_extension_infers_json(self, tmp_path):
        results = _skipped_results(tmp_path)
        controls = _write_controls(tmp_path, '[controls.x]\ndescription = "d"\n')
        out = tmp_path / "matrix.json"
        assert _run_trace(results, controls, "--output", str(out)).returncode == 0
        json.loads(out.read_text())  # would raise if CSV had been written

    def test_explicit_format_wins_and_warns_on_a_mismatch(self, tmp_path):
        results = _skipped_results(tmp_path)
        controls = _write_controls(tmp_path, '[controls.x]\ndescription = "d"\n')
        out = tmp_path / "matrix.json"
        r = _run_trace(results, controls, "--output", str(out), "--format", "csv")
        assert "does not match" in r.stderr
        assert out.read_text().startswith("control_id,")

    def test_unknown_extension_falls_back_to_csv(self, tmp_path):
        results = _skipped_results(tmp_path)
        controls = _write_controls(tmp_path, '[controls.x]\ndescription = "d"\n')
        out = tmp_path / "matrix.txt"
        _run_trace(results, controls, "--output", str(out))
        assert out.read_text().startswith("control_id,")


class TestMalformedInputIsReportedNotRaised:
    @pytest.mark.parametrize("markers", [None, "control-x", 7, {"a": 1}])
    def test_non_list_markers_is_refused(self, tmp_path, markers):
        """Reading it as untagged would report a gap the suite does not have."""
        p = tmp_path / "results.json"
        p.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "results": [{"nodeid": "t.py::a", "outcome": "passed", "markers": markers}],
                }
            ),
            encoding="utf-8",
        )
        controls = _write_controls(tmp_path, '[controls.x]\ndescription = "d"\n')
        r = _run_trace(p, controls)
        assert r.returncode == 1
        assert "Traceback" not in r.stderr
        assert "expected a list" in r.stderr
        assert "t.py::a" in r.stderr

    def test_a_row_that_is_not_an_object_is_refused(self, tmp_path):
        p = tmp_path / "results.json"
        p.write_text(json.dumps({"schema_version": "1.0", "results": ["nope"]}), encoding="utf-8")
        controls = _write_controls(tmp_path, '[controls.x]\ndescription = "d"\n')
        r = _run_trace(p, controls)
        assert r.returncode == 1
        assert "expected an object" in r.stderr

    def test_absent_markers_is_still_accepted(self, tmp_path):
        """Omitting the key is legal; only a wrong type is refused."""
        p = tmp_path / "results.json"
        p.write_text(
            json.dumps(
                {"schema_version": "1.0", "results": [{"nodeid": "a", "outcome": "passed"}]}
            ),
            encoding="utf-8",
        )
        controls = _write_controls(tmp_path, '[controls.x]\ndescription = "d"\n')
        assert _run_trace(p, controls).returncode == 0

    def test_toml_native_date_is_refused_by_both_formats(self, tmp_path):
        results = _skipped_results(tmp_path)
        controls = _write_controls(
            tmp_path, '[controls.x]\ndescription = "d"\nreference = 2024-01-01\n'
        )
        for extra in ([], ["--format", "json"]):
            r = _run_trace(results, controls, *extra)
            assert r.returncode == 1
            assert "Traceback" not in r.stderr
            assert "expected a string" in r.stderr

    def test_output_to_a_directory_errors_cleanly(self, tmp_path):
        results = _skipped_results(tmp_path)
        controls = _write_controls(tmp_path, '[controls.x]\ndescription = "d"\n')
        target = tmp_path / "adir"
        target.mkdir()
        r = _run_trace(results, controls, "--output", str(target))
        assert r.returncode == 1
        assert "Traceback" not in r.stderr
        assert "could not write" in r.stderr


class TestCsvProvenance:
    def test_csv_rows_carry_the_results_digest(self, tmp_path):
        results = _skipped_results(tmp_path)
        controls = _write_controls(tmp_path, '[controls.x]\ndescription = "d"\n')
        rows = list(csv.DictReader(io.StringIO(_run_trace(results, controls).stdout)))
        expected = hashlib.sha256(results.read_bytes()).hexdigest()
        assert rows[0]["results_sha256"] == expected
