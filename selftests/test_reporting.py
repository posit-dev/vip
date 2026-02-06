"""Tests for vip.reporting module."""

from __future__ import annotations

from vip.reporting import ReportData, TestResult, load_results


class TestTestResult:
    def test_category_from_nodeid(self):
        r = TestResult(nodeid="tests/connect/test_auth.py::test_login", outcome="passed")
        assert r.category == "connect"

    def test_category_from_short_nodeid(self):
        r = TestResult(nodeid="test_something.py::test_it", outcome="passed")
        assert r.category == "unknown"

    def test_category_from_nested_nodeid(self):
        r = TestResult(
            nodeid="tests/workbench/test_sessions.py::test_persist",
            outcome="skipped",
        )
        assert r.category == "workbench"


class TestReportData:
    def test_counts(self):
        rd = ReportData(
            results=[
                TestResult(nodeid="a", outcome="passed"),
                TestResult(nodeid="b", outcome="passed"),
                TestResult(nodeid="c", outcome="failed"),
                TestResult(nodeid="d", outcome="skipped"),
            ]
        )
        assert rd.total == 4
        assert rd.passed == 2
        assert rd.failed == 1
        assert rd.skipped == 1

    def test_empty(self):
        rd = ReportData()
        assert rd.total == 0
        assert rd.passed == 0
        assert rd.failed == 0
        assert rd.skipped == 0

    def test_by_category(self):
        rd = ReportData(
            results=[
                TestResult(nodeid="tests/connect/test_a.py::t1", outcome="passed"),
                TestResult(nodeid="tests/connect/test_b.py::t2", outcome="failed"),
                TestResult(nodeid="tests/workbench/test_c.py::t3", outcome="passed"),
            ]
        )
        cats = rd.by_category()
        assert set(cats.keys()) == {"connect", "workbench"}
        assert len(cats["connect"]) == 2
        assert len(cats["workbench"]) == 1


class TestLoadResults:
    def test_load_sample(self, sample_results_json):
        rd = load_results(sample_results_json)
        assert rd.deployment_name == "Selftest Deployment"
        assert rd.generated_at == "2026-01-15T12:00:00+00:00"
        assert rd.exit_status == 0
        assert rd.total == 5
        assert rd.passed == 3
        assert rd.failed == 1
        assert rd.skipped == 1

    def test_categories(self, sample_results_json):
        rd = load_results(sample_results_json)
        cats = rd.by_category()
        assert "connect" in cats
        assert "workbench" in cats
        assert "prerequisites" in cats
        assert "security" in cats

    def test_markers_preserved(self, sample_results_json):
        rd = load_results(sample_results_json)
        connect_tests = [r for r in rd.results if "connect" in r.markers]
        assert len(connect_tests) == 2
