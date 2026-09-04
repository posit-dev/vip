import json
from datetime import datetime


def test_results_carry_per_test_timestamps(pytester):
    pytester.makepyfile(
        test_stamp="""
        def test_passes():
            assert True

        import pytest

        @pytest.mark.skip(reason="deliberate")
        def test_skipped():
            pass
        """
    )
    report = pytester.path / "results.json"
    pytester.runpytest_subprocess("--vip-report", str(report), "-p", "no:cacheprovider")

    data = json.loads(report.read_text())
    assert data["results"], "expected at least one result"
    for entry in data["results"]:
        started, finished = entry["started_at"], entry["finished_at"]
        assert started is not None and finished is not None
        # Parses as ISO 8601 and is timezone-aware UTC.
        start_dt = datetime.fromisoformat(started)
        finish_dt = datetime.fromisoformat(finished)
        assert start_dt.tzinfo is not None
        assert start_dt.utcoffset().total_seconds() == 0
        assert start_dt <= finish_dt


def test_timestamps_absent_in_old_file_load_as_none(tmp_path):
    from vip.reporting import load_results

    p = tmp_path / "results.json"
    p.write_text(json.dumps({"results": [{"nodeid": "a.py::t", "outcome": "passed"}]}))
    result = load_results(p).results[0]
    assert result.started_at is None
    assert result.finished_at is None
