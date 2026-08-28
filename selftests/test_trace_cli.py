import hashlib
import json
import subprocess
import sys

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
