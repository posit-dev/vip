"""Tests for vip.reporting module."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from vip.reporting import (
    ProductInfo,
    ReportData,
    TestResult,
    load_results,
    load_troubleshooting,
    write_junit_xml,
    write_sarif,
)


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

    def test_malformed_toml_returns_empty(self, tmp_path):
        toml_file = tmp_path / "bad.toml"
        toml_file.write_text("this is not valid [[ toml {{")
        hints = load_troubleshooting(toml_file)
        assert hints == {}


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


class TestNAVersionStatus:
    def test_status_defaults_to_outcome(self):
        r = TestResult(nodeid="a", outcome="passed")
        assert r.status == "passed"

    def test_na_version_field_defaults_false(self):
        r = TestResult(nodeid="a", outcome="skipped")
        assert r.na_version is False
        assert r.status == "skipped"

    def test_status_is_na_version_when_flagged_and_skipped(self):
        r = TestResult(nodeid="a", outcome="skipped", na_version=True)
        assert r.status == "na_version"

    def test_na_version_flag_ignored_unless_outcome_is_skipped(self):
        # na_version should never be set on a non-skip in practice, but the
        # status property must not misreport a passed/failed result as N/A.
        r = TestResult(nodeid="a", outcome="passed", na_version=True)
        assert r.status == "passed"

    def test_load_results_parses_na_version(self, tmp_path):
        import json

        data = {
            "deployment_name": "Test",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "exit_status": 0,
            "products": {},
            "results": [
                {
                    "nodeid": "tests/connect/test_a.py::test_needs_recent",
                    "outcome": "skipped",
                    "duration": 0.0,
                    "markers": ["connect"],
                    "na_version": True,
                },
                {
                    "nodeid": "tests/connect/test_b.py::test_unrelated_skip",
                    "outcome": "skipped",
                    "duration": 0.0,
                    "markers": ["connect"],
                },
            ],
        }
        p = tmp_path / "results.json"
        p.write_text(json.dumps(data))
        rd = load_results(p)
        assert rd.results[0].na_version is True
        assert rd.results[0].status == "na_version"
        assert rd.results[1].na_version is False
        assert rd.results[1].status == "skipped"

    def test_na_version_still_counts_toward_skipped_total(self):
        # Documented decision: na_version results are a distinct *status* for
        # display purposes, but they don't get their own summary count --
        # they still count toward ReportData.skipped since they are, at the
        # pytest outcome level, skips.
        rd = ReportData(
            results=[
                TestResult(nodeid="a", outcome="skipped"),
                TestResult(nodeid="b", outcome="skipped", na_version=True),
            ]
        )
        assert rd.skipped == 2
        assert rd.total == 2


class TestConciseError:
    def test_concise_error_field_default_none(self):
        r = TestResult(nodeid="a", outcome="passed")
        assert r.concise_error is None

    def test_concise_error_loaded_from_json(self, tmp_path):
        import json

        data = {
            "deployment_name": "Test",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "exit_status": 1,
            "products": {},
            "results": [
                {
                    "nodeid": "tests/connect/test_auth.py::test_login",
                    "outcome": "failed",
                    "duration": 1.0,
                    "longrepr": "full traceback here...",
                    "concise_error": "test_login: Login failed",
                    "markers": ["connect"],
                },
                {
                    "nodeid": "tests/connect/test_api.py::test_api",
                    "outcome": "passed",
                    "duration": 0.5,
                    "markers": [],
                },
            ],
        }
        p = tmp_path / "results.json"
        p.write_text(json.dumps(data))
        rd = load_results(p)
        assert rd.results[0].concise_error == "test_login: Login failed"
        assert rd.results[1].concise_error is None


class TestWriteJUnitXml:
    def _sample(self) -> ReportData:
        return ReportData(
            deployment_name="Acme Team",
            generated_at="2026-07-21T12:00:00+00:00",
            results=[
                TestResult(
                    nodeid="tests/connect/test_auth.py::test_login",
                    outcome="passed",
                    duration=1.5,
                    scenario_title="User can log in",
                    feature_description="Connect authentication",
                ),
                TestResult(
                    nodeid="tests/workbench/test_sessions.py::test_start",
                    outcome="failed",
                    duration=0.5,
                    concise_error="test_start: TimeoutError session did not start",
                    scenario_title="Session starts",
                    feature_description="Workbench sessions",
                ),
                TestResult(
                    nodeid="tests/connect/test_api.py::test_v1",
                    outcome="skipped",
                    na_version=True,
                    scenario_title="API v1 available",
                ),
            ],
        )

    def test_writes_well_formed_xml_with_counts(self, tmp_path):
        out = tmp_path / "junit.xml"
        write_junit_xml(self._sample(), out)
        tree = ET.parse(out)
        suite = tree.getroot().find("testsuite")
        assert suite.get("tests") == "3"
        assert suite.get("failures") == "1"
        assert suite.get("skipped") == "1"

    def test_failure_carries_concise_error(self, tmp_path):
        out = tmp_path / "junit.xml"
        write_junit_xml(self._sample(), out)
        tree = ET.parse(out)
        cases = {c.get("name"): c for c in tree.getroot().iter("testcase")}
        failed = cases["Session starts"]
        failure = failed.find("failure")
        assert failure is not None
        assert "TimeoutError" in failure.get("message")
        assert failed.get("classname") == "Workbench sessions"

    def test_skip_uses_nodeid_when_no_scenario(self, tmp_path):
        out = tmp_path / "junit.xml"
        write_junit_xml(self._sample(), out)
        tree = ET.parse(out)
        cases = {c.get("name"): c for c in tree.getroot().iter("testcase")}
        assert cases["API v1 available"].find("skipped") is not None
        # passed case has no failure/skipped child
        assert cases["User can log in"].find("failure") is None
        assert cases["User can log in"].find("skipped") is None

    def test_name_and_classname_fall_back_to_nodeid_and_category(self, tmp_path):
        out = tmp_path / "junit.xml"
        data = ReportData(
            results=[
                TestResult(
                    nodeid="tests/connect/test_x.py::test_y",
                    outcome="passed",
                ),
            ],
        )
        write_junit_xml(data, out)
        tree = ET.parse(out)
        case = tree.getroot().find(".//testcase")
        assert case.get("name") == "tests/connect/test_x.py::test_y"
        assert case.get("classname") == "connect"


class TestWriteSarif:
    def _sample(self) -> ReportData:
        return ReportData(
            results=[
                TestResult(
                    nodeid="tests/connect/test_auth.py::test_login",
                    outcome="passed",
                    scenario_title="User can log in",
                ),
                TestResult(
                    nodeid="tests/workbench/test_sessions.py::test_start",
                    outcome="failed",
                    concise_error="test_start: session did not start",
                    scenario_title="Session starts",
                ),
                TestResult(
                    nodeid="tests/connect/test_api.py::test_v1",
                    outcome="skipped",
                    na_version=True,
                    scenario_title="API v1 available",
                ),
            ],
        )

    def test_valid_sarif_envelope(self, tmp_path):
        out = tmp_path / "results.sarif"
        write_sarif(self._sample(), out)
        doc = json.loads(out.read_text())
        assert doc["version"] == "2.1.0"
        assert doc["runs"][0]["tool"]["driver"]["name"] == "vip"
        assert len(doc["runs"][0]["results"]) == 3

    def test_level_mapping_per_outcome(self, tmp_path):
        out = tmp_path / "results.sarif"
        write_sarif(self._sample(), out)
        doc = json.loads(out.read_text())
        levels = {r["ruleId"]: r["level"] for r in doc["runs"][0]["results"]}
        assert levels["tests/connect/test_auth.py::test_login"] == "none"
        assert levels["tests/workbench/test_sessions.py::test_start"] == "error"
        assert levels["tests/connect/test_api.py::test_v1"] == "note"

    def test_rules_deduped_and_logical_location(self, tmp_path):
        out = tmp_path / "results.sarif"
        data = self._sample()
        data.results.append(
            TestResult(nodeid="tests/connect/test_auth.py::test_login", outcome="passed")
        )
        write_sarif(data, out)
        doc = json.loads(out.read_text())
        rule_ids = [r["id"] for r in doc["runs"][0]["tool"]["driver"]["rules"]]
        assert rule_ids.count("tests/connect/test_auth.py::test_login") == 1
        failed = next(
            r
            for r in doc["runs"][0]["results"]
            if r["ruleId"] == "tests/workbench/test_sessions.py::test_start"
        )
        loc = failed["locations"][0]["logicalLocations"][0]["name"]
        assert loc == "workbench / Session starts"
        assert failed["message"]["text"] == "test_start: session did not start"
