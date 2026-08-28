import json

from vip.reporting import RESULTS_SCHEMA_VERSION, load_results


def test_schema_version_is_loaded(tmp_path):
    p = tmp_path / "results.json"
    p.write_text(json.dumps({"schema_version": "1.0", "results": []}))
    assert load_results(p).schema_version == "1.0"


def test_pre_1_0_results_load_with_null_schema_version(tmp_path):
    """An archived results.json written before versioning must still load."""
    p = tmp_path / "results.json"
    p.write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:00:00+00:00",
                "results": [{"nodeid": "a.py::test_x", "outcome": "passed"}],
            }
        )
    )
    data = load_results(p)
    assert data.schema_version is None
    assert len(data.results) == 1


def test_current_schema_version_constant():
    assert RESULTS_SCHEMA_VERSION == "1.0"
