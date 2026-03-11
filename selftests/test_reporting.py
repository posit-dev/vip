"""Tests for vip.reporting module."""

from __future__ import annotations

from vip.reporting import ProductInfo, ReportData, TestResult, load_results, load_troubleshooting


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

    def test_optional_fields_default_none(self):
        r = TestResult(nodeid="a", outcome="passed")
        assert r.scenario_title is None
        assert r.feature_description is None

    def test_optional_fields_set(self):
        r = TestResult(
            nodeid="a",
            outcome="passed",
            scenario_title="User can log in",
            feature_description="Connect authentication",
        )
        assert r.scenario_title == "User can log in"
        assert r.feature_description == "Connect authentication"


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

    def test_products_loaded(self, sample_results_json):
        rd = load_results(sample_results_json)
        assert len(rd.products) == 3
        names = {p.name for p in rd.products}
        assert names == {"connect", "workbench", "package_manager"}

    def test_configured_products(self, sample_results_json):
        rd = load_results(sample_results_json)
        configured = rd.configured_products()
        assert len(configured) == 2
        names = {p.name for p in configured}
        assert names == {"connect", "package_manager"}

    def test_product_version(self, sample_results_json):
        rd = load_results(sample_results_json)
        connect = next(p for p in rd.products if p.name == "connect")
        assert connect.version == "2024.09.0"
        assert connect.url == "https://connect.example.com"

    def test_generated_at_display(self, sample_results_json):
        rd = load_results(sample_results_json)
        display = rd.generated_at_display
        assert "2026" in display
        assert "N/A" not in display

    def test_missing_file_returns_empty(self, tmp_path):
        rd = load_results(tmp_path / "nonexistent.json")
        assert rd.total == 0
        assert rd.deployment_name == "Posit Team"
        assert rd.products == []

    def test_load_with_optional_fields(self, tmp_path):
        import json

        data = {
            "deployment_name": "Test",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "exit_status": 0,
            "products": {},
            "results": [
                {
                    "nodeid": "tests/connect/test_auth.py::test_login",
                    "outcome": "failed",
                    "duration": 1.0,
                    "longrepr": "AssertionError",
                    "markers": ["connect"],
                    "scenario_title": "User can log in via the web UI",
                    "feature_description": "Connect authentication",
                },
                {
                    "nodeid": "tests/connect/test_auth.py::test_api",
                    "outcome": "passed",
                    "duration": 0.5,
                    "markers": ["connect"],
                },
            ],
        }
        p = tmp_path / "results.json"
        p.write_text(json.dumps(data))
        rd = load_results(p)
        assert rd.results[0].scenario_title == "User can log in via the web UI"
        assert rd.results[0].feature_description == "Connect authentication"
        assert rd.results[1].scenario_title is None
        assert rd.results[1].feature_description is None


class TestLoadTroubleshooting:
    def test_load_valid_toml(self, tmp_path):
        toml_file = tmp_path / "troubleshooting.toml"
        toml_file.write_text(
            '["Connect server is reachable"]\n'
            'summary = "Verifies HTTP connectivity"\n'
            'likely_causes = ["Connect is not running", "Wrong URL"]\n'
            'suggested_steps = ["Check systemctl status"]\n'
            'docs_url = "https://docs.example.com"\n'
        )
        hints = load_troubleshooting(toml_file)
        assert "Connect server is reachable" in hints
        entry = hints["Connect server is reachable"]
        assert entry["summary"] == "Verifies HTTP connectivity"
        assert len(entry["likely_causes"]) == 2
        assert len(entry["suggested_steps"]) == 1
        assert entry["docs_url"] == "https://docs.example.com"

    def test_missing_file_returns_empty(self, tmp_path):
        hints = load_troubleshooting(tmp_path / "nonexistent.toml")
        assert hints == {}

    def test_multiple_scenarios(self, tmp_path):
        toml_file = tmp_path / "troubleshooting.toml"
        toml_file.write_text(
            '["Scenario A"]\nsummary = "A"\nlikely_causes = []\nsuggested_steps = []\n\n'
            '["Scenario B"]\nsummary = "B"\nlikely_causes = []\nsuggested_steps = []\n'
        )
        hints = load_troubleshooting(toml_file)
        assert len(hints) == 2
        assert "Scenario A" in hints
        assert "Scenario B" in hints


class TestProductInfo:
    def test_defaults(self):
        p = ProductInfo()
        assert p.name == ""
        assert not p.configured
        assert p.version is None

    def test_from_data(self):
        p = ProductInfo(
            name="connect",
            enabled=True,
            url="https://connect.example.com",
            version="2024.09.0",
            configured=True,
        )
        assert p.name == "connect"
        assert p.configured
        assert p.version == "2024.09.0"
