"""Tests for vip.plugin module."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from vip.plugin import _extract_exception_info, _format_concise_error, _version_tuple


class TestFormatConciseError:
    def test_assertion_with_message(self):
        result = _format_concise_error(
            nodeid="tests/prerequisites/test_auth.py::test_credentials_provided",
            exc_type="AssertionError",
            exc_message=(
                "VIP_TEST_USERNAME is not set. Set it in vip.toml or as an environment variable."
            ),
        )
        assert result == (
            "test_credentials_provided: VIP_TEST_USERNAME is not set."
            " Set it in vip.toml or as an environment variable."
        )

    def test_assertion_without_message(self):
        result = _format_concise_error(
            nodeid="tests/connect/test_auth.py::test_login",
            exc_type="AssertionError",
            exc_message="assert 403 == 200",
        )
        assert result == "test_login: AssertionError: assert 403 == 200"

    def test_unexpected_error(self):
        result = _format_concise_error(
            nodeid="tests/connect/test_deploy.py::test_deploy_app",
            exc_type="ConnectionError",
            exc_message="Connection refused",
        )
        assert result == (
            "test_deploy_app: an unexpected error occurred: ConnectionError: Connection refused"
        )

    def test_unexpected_error_with_dotted_type(self):
        result = _format_concise_error(
            nodeid="tests/connect/test_api.py::test_api_call",
            exc_type="httpx.ConnectError",
            exc_message="[Errno 61] Connection refused",
        )
        assert result == (
            "test_api_call: an unexpected error occurred:"
            " httpx.ConnectError: [Errno 61] Connection refused"
        )

    def test_parametrized_test_name(self):
        result = _format_concise_error(
            nodeid="tests/connect/test_packages.py::test_package_available[numpy]",
            exc_type="AssertionError",
            exc_message="Package numpy not found",
        )
        assert result == "test_package_available[numpy]: Package numpy not found"

    def test_empty_message_assertion_falls_back(self):
        result = _format_concise_error(
            nodeid="tests/connect/test_auth.py::test_login",
            exc_type="AssertionError",
            exc_message="",
        )
        assert result == "test_login: AssertionError"

    def test_empty_message_unexpected_error(self):
        result = _format_concise_error(
            nodeid="tests/connect/test_api.py::test_api_call",
            exc_type="ConnectionError",
            exc_message="",
        )
        assert result == "test_api_call: an unexpected error occurred: ConnectionError"


class TestExtractExceptionInfo:
    def test_from_reprcrash_string(self):
        """Parse a longrepr string that looks like pytest's crash repr."""
        longrepr = (
            "src/vip_tests/prerequisites/test_auth.py:15: in test_credentials\n"
            "E   AssertionError: VIP_TEST_USERNAME is not set."
        )
        exc_type, exc_message = _extract_exception_info(longrepr)
        assert exc_type == "AssertionError"
        assert exc_message == "VIP_TEST_USERNAME is not set."

    def test_from_simple_string(self):
        longrepr = "AssertionError: HTTP not redirected"
        exc_type, exc_message = _extract_exception_info(longrepr)
        assert exc_type == "AssertionError"
        assert exc_message == "HTTP not redirected"

    def test_dotted_exception_type(self):
        longrepr = (
            "tests/connect/test_api.py:42: in test_call\n"
            "E   httpx.ConnectError: [Errno 61] Connection refused"
        )
        exc_type, exc_message = _extract_exception_info(longrepr)
        assert exc_type == "httpx.ConnectError"
        assert exc_message == "[Errno 61] Connection refused"

    def test_bare_assertion(self):
        longrepr = (
            "tests/connect/test_auth.py:10: in test_login\nE   AssertionError: assert 403 == 200"
        )
        exc_type, exc_message = _extract_exception_info(longrepr)
        assert exc_type == "AssertionError"
        assert exc_message == "assert 403 == 200"

    def test_bare_assert_no_type_prefix(self):
        """pytest assertion rewriting produces 'E   assert ...' without AssertionError prefix."""
        longrepr = (
            "tests/connect/test_auth.py:10: in test_login\n"
            "E       assert 403 == 200\n"
            "E        +  where 403 = response.status_code"
        )
        exc_type, exc_message = _extract_exception_info(longrepr)
        assert exc_type == "AssertionError"
        assert exc_message == "assert 403 == 200"

    def test_empty_message_after_type(self):
        """ExcType with colon but no message text."""
        longrepr = "tests/test_foo.py:5: in test_it\nE   ValueError:"
        exc_type, exc_message = _extract_exception_info(longrepr)
        assert exc_type == "ValueError"
        assert exc_message == ""

    def test_unknown_format_falls_back(self):
        longrepr = "something weird happened"
        exc_type, exc_message = _extract_exception_info(longrepr)
        assert exc_type == "UnknownError"
        assert exc_message == "something weird happened"

    def test_multiline_message(self):
        longrepr = "tests/test_foo.py:5: in test_it\nE   ValueError: line one\nE   line two"
        exc_type, exc_message = _extract_exception_info(longrepr)
        assert exc_type == "ValueError"
        assert exc_message == "line one"


class TestVersionTuple:
    def test_simple(self):
        assert _version_tuple("1.2.3") == (1, 2, 3)

    def test_two_part(self):
        assert _version_tuple("2024.05") == (2024, 5)

    def test_prerelease_suffix(self):
        assert _version_tuple("1.2.3rc1") == (1, 2, 3)

    def test_single_number(self):
        assert _version_tuple("42") == (42,)

    def test_comparison(self):
        assert _version_tuple("2024.05.0") < _version_tuple("2024.06.0")
        assert _version_tuple("2024.05.0") == _version_tuple("2024.05.0")
        assert _version_tuple("1.0.0") < _version_tuple("2.0.0")
        assert _version_tuple("1.9.9") < _version_tuple("1.10.0")


class TestPluginIntegration:
    """Integration tests using pytester to exercise the plugin end-to-end.

    pytester runs pytest in a subprocess, so each invocation gets its own
    plugin state (including a fresh ``_results`` list).
    """

    @pytest.fixture()
    def selftest_pytester(self, pytester):
        """pytester fixture pre-configured with VIP installed."""
        # Write a minimal vip.toml that has no products configured so all
        # product-marked tests get skipped.
        pytester.makefile(".toml", vip='[general]\ndeployment_name = "Selftest"')
        return pytester

    def test_unconfigured_product_deselected(self, selftest_pytester):
        selftest_pytester.makepyfile(
            """
            import pytest

            @pytest.mark.connect
            def test_needs_connect():
                assert True
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes()
        result.stdout.fnmatch_lines(["*1 deselected*"])

    def test_version_skip(self, selftest_pytester):
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
        # Connect has no version set, so the test runs optimistically.
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.stdout.fnmatch_lines(["*PASSED*"])

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

    def test_extension_dirs_collected(self, selftest_pytester, tmp_path):
        ext_dir = tmp_path / "ext_tests"
        ext_dir.mkdir()
        (ext_dir / "test_extra.py").write_text("def test_from_extension():\n    assert True\n")

        selftest_pytester.makepyfile(
            """
            def test_base():
                assert True
            """
        )
        result = selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-extensions={ext_dir}",
            "-v",
        )
        result.stdout.fnmatch_lines(["*test_from_extension*PASSED*"])

    def test_markers_registered(self, selftest_pytester):
        result = selftest_pytester.runpytest("--markers")
        result.stdout.fnmatch_lines(
            [
                "*connect*",
                "*workbench*",
                "*package_manager*",
                "*min_version*",
            ]
        )

    def test_interactive_auth_option_registered(self, selftest_pytester):
        """--interactive-auth appears in help output."""
        result = selftest_pytester.runpytest("--help")
        result.stdout.fnmatch_lines(["*--interactive-auth*"])

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

    def test_interactive_auth_requires_product_url(self, selftest_pytester):
        """--interactive-auth fails fast when no product URL is configured."""
        selftest_pytester.makepyfile(
            """
            def test_placeholder():
                assert True
            """
        )
        result = selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            "--interactive-auth",
        )
        result.stderr.fnmatch_lines(["*--interactive-auth requires at least one product URL*"])

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
        assert "Config is missing" in data["failures"][0]["error_summary"]
        # Should be the concise format, not a 500-char truncation
        assert len(data["failures"][0]["error_summary"]) < 200

    def test_concise_failure_output(self, selftest_pytester):
        """Failed test shows one-liner, not full traceback."""
        selftest_pytester.makepyfile(
            """
            def test_with_message():
                assert False, "Username is missing"
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes(failed=1)
        # The concise message should appear in output.
        result.stdout.fnmatch_lines(["*Username is missing*"])
        # The full traceback should NOT appear — no "E" prefix lines with AssertionError.
        for line in result.stdout.lines:
            assert not (line.lstrip().startswith("E") and "AssertionError" in line), (
                f"Found unexpected traceback line: {line}"
            )

    def test_concise_mode_suppresses_short_summary(self, selftest_pytester):
        """Concise mode hides the 'short test summary info' section."""
        selftest_pytester.makepyfile(
            """
            def test_fails():
                assert False, "expected failure"
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes(failed=1)
        result.stdout.no_fnmatch_line("*short test summary info*")

    def test_vip_verbose_shows_short_summary(self, selftest_pytester):
        """--vip-verbose keeps the 'short test summary info' section."""
        selftest_pytester.makepyfile(
            """
            def test_fails():
                assert False, "expected failure"
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "--vip-verbose", "-v")
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*short test summary info*"])

    def test_unexpected_error_output(self, selftest_pytester):
        """Non-assertion errors show 'an unexpected error occurred' prefix."""
        selftest_pytester.makepyfile(
            """
            def test_crashes():
                raise ValueError("bad value")
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*an unexpected error occurred*ValueError*bad value*"])

    def test_vip_verbose_shows_full_traceback(self, selftest_pytester):
        """--vip-verbose restores pytest's default traceback output."""
        selftest_pytester.makepyfile(
            """
            def test_with_message():
                assert False, "Username is missing"
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "--vip-verbose", "-v")
        result.assert_outcomes(failed=1)
        # Full traceback should appear — look for pytest's "E" prefix lines.
        # The exact number of spaces varies by pytest version, so match loosely.
        assert any(
            line.lstrip().startswith("E") and "AssertionError" in line
            for line in result.stdout.lines
        ), "Expected a traceback 'E ... AssertionError' line in verbose output"

    def test_concise_empty_message_exception(self, selftest_pytester):
        """Non-assertion exception with no message gets 'unexpected error' prefix."""
        selftest_pytester.makepyfile(
            """
            def test_empty_value_error():
                raise ValueError()
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes(failed=1)
        result.stdout.fnmatch_lines(["*an unexpected error occurred*ValueError*"])

    def test_concise_output_end_to_end(self, selftest_pytester):
        """Full flow: concise terminal output + JSON report with both fields."""
        selftest_pytester.makepyfile(
            """
            def test_passes():
                assert True

            def test_assertion_fails():
                assert False, "Deployment check failed"

            def test_error_fails():
                raise RuntimeError("connection lost")
            """
        )
        report_path = selftest_pytester.path / "results.json"
        result = selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
            "-v",
        )
        result.assert_outcomes(passed=1, failed=2)

        # Terminal: concise output
        result.stdout.fnmatch_lines(["*Deployment check failed*"])
        result.stdout.fnmatch_lines(["*an unexpected error occurred*RuntimeError*connection lost*"])

        # JSON: both fields present for failures
        data = json.loads(report_path.read_text())
        failed = [r for r in data["results"] if r["outcome"] == "failed"]
        for r in failed:
            assert r["concise_error"] is not None
            assert r["longrepr"] is not None
            # longrepr contains traceback details; concise_error is a one-liner
            assert "Traceback" in r["longrepr"] or ".py" in r["longrepr"]
            assert "::" not in r["concise_error"]  # no nodeid path, just test name

        # Passing tests have no concise_error
        passed = [r for r in data["results"] if r["outcome"] == "passed"]
        for r in passed:
            assert r["concise_error"] is None


class TestXdistCompatibility:
    """Verify that JSON report generation works with and without xdist."""

    @pytest.fixture()
    def selftest_pytester(self, pytester):
        pytester.makefile(".toml", vip='[general]\ndeployment_name = "Selftest"')
        return pytester

    def test_json_report_with_xdist(self, selftest_pytester):
        """Results JSON is populated when running with -n auto."""
        selftest_pytester.makepyfile(
            """
            def test_one():
                assert True

            def test_two():
                assert True

            def test_three():
                assert False, "intentional failure"
            """
        )
        report_path = selftest_pytester.path / "results.json"
        result = selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
            "-n",
            "auto",
            "--dist",
            "loadgroup",
        )
        result.assert_outcomes(passed=2, failed=1)
        assert report_path.exists()

        data = json.loads(report_path.read_text())
        assert len(data["results"]) == 3
        passed = [r for r in data["results"] if r["outcome"] == "passed"]
        failed = [r for r in data["results"] if r["outcome"] == "failed"]
        assert len(passed) == 2
        assert len(failed) == 1
        assert failed[0]["concise_error"] is not None
        assert failed[0]["longrepr"] is not None

    def test_json_report_without_xdist(self, selftest_pytester):
        """Results JSON is still populated with -n 0 (xdist disabled)."""
        selftest_pytester.makepyfile(
            """
            def test_passes():
                assert True

            def test_fails():
                assert False, "expected"
            """
        )
        report_path = selftest_pytester.path / "results.json"
        result = selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
            "-n",
            "0",
        )
        result.assert_outcomes(passed=1, failed=1)
        assert report_path.exists()

        data = json.loads(report_path.read_text())
        assert len(data["results"]) == 2

    def test_vip_metadata_survives_xdist(self, selftest_pytester):
        """Custom report attributes (markers, scenario fields) survive xdist transit."""
        selftest_pytester.makepyfile(
            """
            import pytest

            @pytest.mark.connect
            def test_with_marker():
                assert True
            """
        )
        # Connect not configured → test gets deselected, but we need a passing test.
        # Use a plain test and check markers are present in results.
        selftest_pytester.makepyfile(
            test_plain="""
            def test_plain():
                assert True
            """
        )
        report_path = selftest_pytester.path / "results.json"
        result = selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
            "-n",
            "auto",
            "--dist",
            "loadgroup",
            "test_plain.py",
        )
        result.assert_outcomes(passed=1)

        data = json.loads(report_path.read_text())
        assert len(data["results"]) == 1
        r = data["results"][0]
        assert "markers" in r
        assert isinstance(r["markers"], list)
        assert "scenario_title" in r
        assert "feature_description" in r


def test_markers_in_sync():
    """Markers in pyproject.toml match those registered in plugin.py."""
    repo_root = Path(__file__).parent.parent

    # Parse marker names from pyproject.toml [tool.pytest.ini_options] markers list.
    # Each entry looks like: "name: description" or "name(args): description"
    pyproject_text = (repo_root / "pyproject.toml").read_text()
    markers_section = re.search(
        r"\[tool\.pytest\.ini_options\].*?^markers\s*=\s*\[(.*?)\]",
        pyproject_text,
        re.DOTALL | re.MULTILINE,
    )
    assert markers_section, "Could not find markers list in pyproject.toml"
    pyproject_markers = set(
        re.match(r"\s*['\"](\w+)", line).group(1)
        for line in markers_section.group(1).splitlines()
        if re.match(r"\s*['\"](\w+)", line)
    )

    # Parse marker names registered via config.addinivalue_line in plugin.py.
    # Each call looks like:
    #   config.addinivalue_line("markers", "name...")          (single-line)
    #   config.addinivalue_line(\n    "markers",\n    "name..."\n)  (multi-line)
    plugin_text = (repo_root / "src" / "vip" / "plugin.py").read_text()
    plugin_markers = set(
        re.match(r"(\w+)", m).group(1)
        for m in re.findall(
            r'addinivalue_line\(\s*["\']markers["\'],\s*["\'](\w[^"\']*)["\']',
            plugin_text,
            re.DOTALL,
        )
    )

    assert pyproject_markers == plugin_markers, (
        f"Marker mismatch between pyproject.toml and plugin.py.\n"
        f"  Only in pyproject.toml: {pyproject_markers - plugin_markers}\n"
        f"  Only in plugin.py:      {plugin_markers - pyproject_markers}"
    )
