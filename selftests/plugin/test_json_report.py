"""Tests for vip.plugin module — JSON report content."""

from __future__ import annotations

import json


class TestPluginIntegration:
    """Integration tests using pytester to exercise the plugin end-to-end.

    pytester runs pytest in a subprocess, so each invocation gets its own
    plugin state (including a fresh ``_results`` list).
    """

    def test_json_report_output(self, selftest_pytester):
        selftest_pytester.makepyfile(
            """
            def test_always_passes():
                assert True
            """
        )
        report_path = selftest_pytester.path / "results.json"
        result = selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
        )
        result.assert_outcomes(passed=1)
        assert report_path.exists()

        data = json.loads(report_path.read_text())
        assert data["deployment_name"] == "Selftest"
        assert data["exit_status"] == 0
        # The subprocess should only see the single test it ran.
        passed_results = [r for r in data["results"] if r["outcome"] == "passed"]
        assert len(passed_results) >= 1
        assert any("test_always_passes" in r["nodeid"] for r in passed_results)

    def test_json_report_includes_scenario_fields(self, selftest_pytester):
        """Results JSON includes scenario_title and feature_description keys."""
        selftest_pytester.makepyfile(
            """
            def test_plain():
                assert True
            """
        )
        report_path = selftest_pytester.path / "results.json"
        selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
        )
        data = json.loads(report_path.read_text())
        result = data["results"][0]
        # Non-BDD tests should have the keys present but set to None.
        assert "scenario_title" in result
        assert "feature_description" in result
        assert result["scenario_title"] is None
        assert result["feature_description"] is None

    def test_json_report_includes_na_version_flag(self, selftest_pytester):
        """Results JSON flags version-unknown skips with na_version: true."""
        selftest_pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n[connect]\nurl = "https://example.com"\n'
            ),
        )
        selftest_pytester.makepyfile(
            """
            import pytest

            @pytest.mark.min_version(product="connect", version="9999.01.0")
            def test_future_version():
                assert True
            """
        )
        report_path = selftest_pytester.path / "results.json"
        selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
        )
        data = json.loads(report_path.read_text())
        result = data["results"][0]
        assert result["outcome"] == "skipped"
        assert result["na_version"] is True

    def test_json_report_na_version_defaults_false(self, selftest_pytester):
        """Ordinary results (including ordinary skips) report na_version: false."""
        selftest_pytester.makepyfile(
            """
            def test_plain():
                assert True
            """
        )
        report_path = selftest_pytester.path / "results.json"
        selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
        )
        data = json.loads(report_path.read_text())
        result = data["results"][0]
        assert result["na_version"] is False

    def test_json_report_includes_skip_reason(self, selftest_pytester):
        """A marker-skipped test's reason lands in skip_reason, and longrepr is
        dropped rather than storing pytest's absolute-path-carrying tuple form.
        """
        selftest_pytester.makepyfile(
            """
            import pytest

            @pytest.mark.skip(reason="high-concurrency localhost loads are flaky")
            def test_skips():
                pass
            """
        )
        report_path = selftest_pytester.path / "results.json"
        selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
        )
        data = json.loads(report_path.read_text())
        result = data["results"][0]
        assert result["outcome"] == "skipped"
        assert result["skip_reason"] == "high-concurrency localhost loads are flaky"
        assert result["longrepr"] is None

    def test_json_report_na_version_skip_also_gets_skip_reason(self, selftest_pytester):
        """na_version skips (see _skip_version_unknown) are still skips, so they
        get a skip_reason too -- it complements na_version, not replaces it.
        """
        selftest_pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n[connect]\nurl = "https://example.com"\n'
            ),
        )
        selftest_pytester.makepyfile(
            """
            import pytest

            @pytest.mark.min_version(product="connect", version="9999.01.0")
            def test_future_version():
                assert True
            """
        )
        report_path = selftest_pytester.path / "results.json"
        selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
        )
        data = json.loads(report_path.read_text())
        result = data["results"][0]
        assert result["na_version"] is True
        assert result["skip_reason"] is not None
        assert "version unknown for connect" in result["skip_reason"]

    def test_json_report_skip_reason_none_for_non_skips(self, selftest_pytester):
        selftest_pytester.makepyfile(
            """
            def test_plain():
                assert True
            """
        )
        report_path = selftest_pytester.path / "results.json"
        selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
        )
        data = json.loads(report_path.read_text())
        assert data["results"][0]["skip_reason"] is None

    def test_json_report_failure_longrepr_unaffected_by_skip_change(self, selftest_pytester):
        """Dropping longrepr is specific to skips -- a failure still gets one."""
        selftest_pytester.makepyfile(
            """
            def test_fails():
                assert False, "boom"
            """
        )
        report_path = selftest_pytester.path / "results.json"
        selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
        )
        data = json.loads(report_path.read_text())
        result = data["results"][0]
        assert result["outcome"] == "failed"
        assert result["longrepr"] is not None
        assert result["skip_reason"] is None

    def test_json_report_includes_provenance_fields(self, selftest_pytester):
        """F9: results.json records the version/duration/environment that
        produced it.
        """
        import platform as _platform

        selftest_pytester.makepyfile(
            """
            def test_plain():
                assert True
            """
        )
        report_path = selftest_pytester.path / "results.json"
        selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
        )
        data = json.loads(report_path.read_text())
        from vip import __version__ as vip_version

        assert data["vip_version"] == vip_version
        # This pytester run executes in-process (runpytest, not
        # runpytest_subprocess), so it shares this test's own interpreter --
        # the recorded python_version/platform must match it exactly.
        assert data["python_version"] == _platform.python_version()
        assert data["platform"] == _platform.platform()
        assert isinstance(data["run_duration_seconds"], float)
        assert data["run_duration_seconds"] >= 0
        assert data["basic_mode"] is False

    def test_json_report_basic_mode_true_when_slow_marker_excluded(self, selftest_pytester):
        """basic_mode reflects the resolved marker expression, not a dedicated
        flag -- `vip verify --basic` and a hand-written `-m "not slow"` both
        set it, because both actually excluded the slow marker.
        """
        selftest_pytester.makepyfile(
            """
            def test_plain():
                assert True
            """
        )
        report_path = selftest_pytester.path / "results.json"
        selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
            "-m",
            "not slow",
        )
        data = json.loads(report_path.read_text())
        assert data["basic_mode"] is True

    def test_json_report_includes_concise_error(self, selftest_pytester):
        selftest_pytester.makepyfile(
            """
            def test_expected_failure():
                assert False, "Something went wrong"

            def test_unexpected_failure():
                raise ValueError("bad value")
            """
        )
        report_path = selftest_pytester.path / "results.json"
        result = selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
        )
        result.assert_outcomes(failed=2)

        data = json.loads(report_path.read_text())
        failed = [r for r in data["results"] if r["outcome"] == "failed"]
        assert len(failed) == 2

        expected = next(r for r in failed if "expected_failure" in r["nodeid"])
        assert expected["concise_error"] is not None
        assert "Something went wrong" in expected["concise_error"]
        assert expected["longrepr"] is not None  # full traceback preserved

        unexpected = next(r for r in failed if "unexpected_failure" in r["nodeid"])
        assert "an unexpected error occurred" in unexpected["concise_error"]
        assert "ValueError" in unexpected["concise_error"]

    def test_failures_json_uses_concise_error(self, selftest_pytester):
        selftest_pytester.makepyfile(
            """
            def test_will_fail():
                assert False, "Config is missing"
            """
        )
        report_path = selftest_pytester.path / "results.json"
        selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
        )
        failures_path = selftest_pytester.path / "failures.json"
        assert failures_path.exists()

        data = json.loads(failures_path.read_text())
        assert len(data["failures"]) == 1
        error_summary = data["failures"][0]["error_summary"]
        assert "Config is missing" in error_summary
        # Validate the concise format is used (not the raw longrepr fallback).
        # No hard character-count limit — multi-line summaries may legitimately exceed 200 chars.
        assert "FAILED" not in error_summary, "error_summary should be concise, not raw longrepr"
