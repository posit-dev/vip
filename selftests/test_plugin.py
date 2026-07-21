"""Tests for vip.plugin module."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from vip.plugin import (
    _extract_exception_info,
    _format_concise_error,
    _outcome_color,
    _shorten_location_line,
)


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
        longrepr = "tests/test_foo.py:5: in test_it\nE   ValueError: line one\nE       line two"
        exc_type, exc_message = _extract_exception_info(longrepr)
        assert exc_type == "ValueError"
        assert exc_message == "line one\nline two"

    def test_multiline_assertion_with_details(self):
        """Multi-line assertion messages should include continuation lines."""
        longrepr = (
            "tests/test_foo.py:5: in test_it\n"
            "E       AssertionError: Prometheus metrics endpoint check failed:\n"
            "E         Connect: /metrics returned 403 (expected 200)"
        )
        exc_type, exc_message = _extract_exception_info(longrepr)
        assert exc_type == "AssertionError"
        assert "Connect: /metrics returned 403" in exc_message


class TestOutcomeColor:
    """Per-line progress-indicator color derived from a single report."""

    class _Rep:
        def __init__(self, when, *, passed=False, failed=False, skipped=False, wasxfail=False):
            self.when = when
            self.passed = passed
            self.failed = failed
            self.skipped = skipped
            if wasxfail:
                self.wasxfail = ""

    def test_passed_call_is_green(self):
        assert _outcome_color(self._Rep("call", passed=True)) == "green"

    def test_failed_call_is_red(self):
        assert _outcome_color(self._Rep("call", failed=True)) == "red"

    def test_skipped_setup_is_yellow(self):
        assert _outcome_color(self._Rep("setup", skipped=True)) == "yellow"

    def test_xfail_call_is_yellow(self):
        assert _outcome_color(self._Rep("call", skipped=True, wasxfail=True)) == "yellow"

    def test_passing_setup_phase_is_ignored(self):
        assert _outcome_color(self._Rep("setup", passed=True)) is None

    def test_teardown_phase_is_ignored(self):
        assert _outcome_color(self._Rep("teardown", passed=True)) is None


class TestShortenLocationLine:
    def test_strips_site_packages_prefix(self):
        line = (
            "../../../../.local/share/uv/tools/posit-vip/lib/python3.13/"
            "site-packages/vip_tests/connect/test_auth.py::test_connect_login_ui "
        )
        assert _shorten_location_line(line) == "connect/test_auth.py::test_connect_login_ui "

    def test_keeps_relative_suffix_and_trailing_space(self):
        line = "vip_tests/prerequisites/test_components.py::test_reachable[Connect] "
        assert (
            _shorten_location_line(line)
            == "prerequisites/test_components.py::test_reachable[Connect] "
        )

    def test_passes_through_line_without_marker(self):
        line = "my_extension/test_health.py::test_ping "
        assert _shorten_location_line(line) == line

    def test_uses_last_marker_occurrence(self):
        # A path that itself contains the marker earlier must not win over the
        # real package root.
        line = "/home/vip_tests/checkout/site-packages/vip_tests/security/test_tls.py::test_https "
        assert _shorten_location_line(line) == "security/test_tls.py::test_https "


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

    def test_slow_deselected_by_not_slow(self, selftest_pytester):
        selftest_pytester.makepyfile(
            """
            import pytest

            @pytest.mark.slow
            def test_a_slow_check():
                assert True
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-m", "not slow", "-v")
        result.stdout.fnmatch_lines(["*1 deselected*"])

    def test_progress_indicator_recolored_per_line(self, selftest_pytester):
        """After a failure, a later passing line's [x%] stays green, not red.

        pytest normally colors the progress indicator with the cumulative
        session color (red once anything fails). We recolor per-line so only
        the failing line's indicator is red.
        """
        selftest_pytester.makepyfile(
            """
            def test_a_pass():
                assert True

            def test_b_fail():
                assert False

            def test_c_pass():
                assert True
            """
        )
        result = selftest_pytester.runpytest_subprocess(
            "--vip-config=vip.toml", "-v", "--color=yes", "-p", "no:randomly"
        )
        result.assert_outcomes(passed=2, failed=1)
        green = "\x1b[32m"
        red = "\x1b[31m"
        # The progress indicator inherits the color opened just before it (the
        # fill spaces sit between the code and the digits), so match the color
        # code + fill + percentage as a regex rather than requiring adjacency.
        c_line = next(line for line in result.outlines if "test_c_pass" in line)
        assert re.search(rf"{re.escape(green)} +\[100%\]", c_line)
        assert not re.search(rf"{re.escape(red)} +\[100%\]", c_line)
        # And the failing line's own indicator is red.
        b_line = next(line for line in result.outlines if "test_b_fail" in line)
        assert re.search(rf"{re.escape(red)} +\[ 66%\]", b_line)

    def test_location_line_shortened_in_concise_mode(self, selftest_pytester):
        """A test collected under a vip_tests/ package shows a truncated path."""
        pkg = selftest_pytester.mkpydir("vip_tests")
        (pkg / "test_sample.py").write_text("def test_ok():\n    assert True\n")
        result = selftest_pytester.runpytest_subprocess(
            "--vip-config=vip.toml", "-v", str(pkg / "test_sample.py")
        )
        result.assert_outcomes(passed=1)
        result.stdout.fnmatch_lines(["test_sample.py::test_ok*"])
        result.stdout.no_fnmatch_line("*vip_tests/test_sample.py::test_ok*")

    def test_location_line_full_path_when_verbose(self, selftest_pytester):
        """--vip-verbose keeps the full node path so debugging is unaffected."""
        pkg = selftest_pytester.mkpydir("vip_tests")
        (pkg / "test_sample.py").write_text("def test_ok():\n    assert True\n")
        result = selftest_pytester.runpytest_subprocess(
            "--vip-config=vip.toml", "--vip-verbose", "-v", str(pkg / "test_sample.py")
        )
        result.assert_outcomes(passed=1)
        result.stdout.fnmatch_lines(["*vip_tests/test_sample.py::test_ok*"])

    def test_pytest_bdd_removed_in10_warning_suppressed(self, selftest_pytester):
        """pytest-bdd's fixture injection emits PytestRemovedIn10Warning on
        pytest >= 9.1 (``_register_fixture(nodeid=...)``/``FixtureDef(baseid=...)``).
        The plugin filters that category so it never reaches users who install
        vip into their own project. We emit the warning directly because the
        repo-pinned pytest does not warn yet, which keeps the check meaningful
        regardless of the installed pytest version.
        """
        selftest_pytester.makepyfile(
            """
            import warnings

            import pytest

            def test_emits_removed_in10():
                warnings.warn(
                    "Passing nodeid to _register_fixture is deprecated.",
                    pytest.PytestRemovedIn10Warning,
                )
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml")
        result.assert_outcomes(passed=1)
        result.stdout.no_fnmatch_line("*PytestRemovedIn10Warning*")

    def test_performance_deselected_by_default(self, selftest_pytester):
        """_default_marker_expr excludes performance when --performance-tests is not set."""
        import argparse

        from vip.cli import _default_marker_expr, _extra_keep_from_args

        args = argparse.Namespace(performance_tests=False)
        expr = _default_marker_expr(_extra_keep_from_args(args))
        assert "not performance" in expr

    def test_performance_runs_with_flag(self, selftest_pytester):
        """_default_marker_expr omits the performance exclusion when --performance-tests is set."""
        import argparse

        from vip.cli import _default_marker_expr, _extra_keep_from_args

        args = argparse.Namespace(performance_tests=True)
        expr = _default_marker_expr(_extra_keep_from_args(args))
        assert "not performance" not in expr

    def test_bdd_given_configured_step_deselected(self, selftest_pytester):
        """A BDD scenario with 'Given Connect is configured in vip.toml'
        should be deselected (not skipped) when Connect is not configured."""
        selftest_pytester.makefile(
            ".feature",
            test_perf=(
                "@performance\n"
                "Feature: Perf test\n"
                "  Scenario: Load test Connect\n"
                "    Given Connect is configured in vip.toml\n"
                "    Then something passes\n"
            ),
        )
        selftest_pytester.makepyfile(
            test_perf="""
            import pytest
            from pytest_bdd import scenario, given, then

            @scenario("test_perf.feature", "Load test Connect")
            def test_load():
                pass

            @given("Connect is configured in vip.toml")
            def connect_configured():
                pytest.skip("Connect is not configured")

            @then("something passes")
            def something_passes():
                pass
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes()
        result.stdout.fnmatch_lines(["*1 deselected*"])
        # Must NOT appear as SKIPPED
        assert "SKIPPED" not in result.stdout.str()

    def test_bdd_given_configured_product_not_deselected(self, selftest_pytester):
        """A BDD scenario with 'Given Connect is configured' should run
        when Connect IS configured."""
        selftest_pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n[connect]\nurl = "https://example.com"\n'
            ),
        )
        selftest_pytester.makefile(
            ".feature",
            test_configured=(
                "@performance\n"
                "Feature: Perf test\n"
                "  Scenario: Load test Connect\n"
                "    Given Connect is configured in vip.toml\n"
                "    Then it passes\n"
            ),
        )
        selftest_pytester.makepyfile(
            test_configured="""
            from pytest_bdd import scenario, given, then

            @scenario("test_configured.feature", "Load test Connect")
            def test_load():
                pass

            @given("Connect is configured in vip.toml")
            def connect_configured():
                pass

            @then("it passes")
            def it_passes():
                pass
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes(passed=1)

    def test_bdd_when_step_not_deselected(self, selftest_pytester):
        """A 'When' step matching a product name should NOT trigger deselection."""
        selftest_pytester.makefile(
            ".feature",
            test_when=(
                "@performance\n"
                "Feature: When step test\n"
                "  Scenario: When Connect is configured check\n"
                "    When Connect is configured in the report\n"
                "    Then it passes\n"
            ),
        )
        selftest_pytester.makepyfile(
            test_when="""
            from pytest_bdd import scenario, when, then

            @scenario("test_when.feature", "When Connect is configured check")
            def test_when_step():
                pass

            @when("Connect is configured in the report")
            def connect_in_report():
                pass

            @then("it passes")
            def it_passes():
                pass
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes(passed=1)
        # Ensure no tests were deselected (check the summary line, not raw text
        # which may contain "deselected" in the tmpdir path).
        assert "deselected" not in result.stdout.lines[-1]

    def test_bdd_parameterized_unconfigured_deselected(self, selftest_pytester):
        """A parameterized '<product> is configured' step should deselect
        when the product is not configured."""
        selftest_pytester.makefile(
            ".feature",
            test_param=(
                "@performance\n"
                "Feature: Param test\n"
                "  Scenario Outline: <product> check\n"
                "    Given <product> is configured in vip.toml\n"
                "    Then it passes\n"
                "\n"
                "    Examples:\n"
                "      | product   |\n"
                "      | Connect   |\n"
                "      | CustomApp |\n"
            ),
        )
        selftest_pytester.makepyfile(
            test_param="""
            import pytest
            from pytest_bdd import scenarios, given, then, parsers

            scenarios("test_param.feature")

            @given(parsers.parse("{product} is configured in vip.toml"))
            def product_configured(product):
                pytest.skip(f"{product} is not configured")

            @then("it passes")
            def it_passes():
                pass
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        # Connect is not configured → deselected.
        # CustomApp is unrecognized → not deselected, runs and skips at runtime.
        result.stdout.fnmatch_lines(["*1 deselected*"])
        result.stdout.fnmatch_lines(["*SKIPPED*"])

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
        # Connect has no version set. This used to run optimistically (PASS);
        # the policy changed so an unknown version skips + warns instead of
        # risking a spurious pass.
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.stdout.fnmatch_lines(["*SKIPPED*"])
        result.stdout.fnmatch_lines(
            ["*VIP: cannot evaluate min_version(product='connect', version='9999.01.0')*"]
        )

    def test_version_skip_unparseable_deployed_version(self, selftest_pytester):
        """An unparseable deployed version also skips + warns, not runs optimistically."""
        selftest_pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n'
                '[connect]\nurl = "https://example.com"\nversion = "not-a-version"\n'
            ),
        )
        selftest_pytester.makepyfile(
            """
            import pytest

            @pytest.mark.min_version(product="connect", version="2024.09.0")
            def test_needs_recent_connect():
                assert True
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.stdout.fnmatch_lines(["*SKIPPED*"])
        result.stdout.fnmatch_lines(
            ["*VIP: cannot evaluate min_version(product='connect', version='2024.09.0')*"]
        )

    def test_version_skip_known_below_minimum_is_plain_skip(self, selftest_pytester):
        """A known deployed version below the minimum is a plain skip, not N/A."""
        selftest_pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n'
                '[connect]\nurl = "https://example.com"\nversion = "2024.01.0"\n'
            ),
        )
        selftest_pytester.makepyfile(
            """
            import pytest

            @pytest.mark.min_version(product="connect", version="2024.09.0")
            def test_needs_recent_connect():
                assert True
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "--vip-verbose", "-v", "-rs")
        result.stdout.fnmatch_lines(["*SKIPPED*"])
        result.stdout.fnmatch_lines(["*connect version 2024.01.0 < required 2024.09.0*"])
        # No N/A warning for this path — the version is known, just too old.
        assert "cannot evaluate min_version" not in result.stdout.str()

    # A skip reason far longer than 80 columns, ending in a unique sentinel so
    # we can tell a full reason from one pytest has ellipsized to "(reason...)".
    _LONG_SKIP_REASON = (
        "Workbench session not established by --interactive-auth so this skip "
        "reason is intentionally far longer than eighty columns and would "
        "normally be ellipsized before the END_OF_REASON_SENTINEL"
    )

    def _make_long_skip_test(self, selftest_pytester):
        selftest_pytester.makepyfile(
            f"""
            import pytest

            @pytest.mark.skip(reason={self._LONG_SKIP_REASON!r})
            def test_skips():
                pass
            """
        )

    def test_skip_reason_shown_in_full_inline(self, selftest_pytester, monkeypatch):
        """A long skip reason renders in full on the verbose (``-v``) test line.

        pytest ellipsizes the inline reason to the terminal width at the default
        test-case verbosity; the plugin bumps that level to 2 under ``-v`` so the
        whole reason is shown (it may wrap, but no text is dropped).
        """
        monkeypatch.setenv("COLUMNS", "80")
        self._make_long_skip_test(selftest_pytester)
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes(skipped=1)
        # Collapse whitespace so a wrapped reason still matches end to end.
        collapsed = "".join(result.stdout.str().split())
        assert "".join(self._LONG_SKIP_REASON.split()) in collapsed
        assert "END_OF_REASON_SENTINEL" in collapsed
        # The ellipsized form pytest would emit at the default verbosity ends in
        # "...)" — its absence proves the bump actually fired (and isn't a silent
        # no-op on a future pytest where the private _inicache write breaks).
        assert "...)" not in collapsed

    def test_skip_reason_ellipsized_without_bump(self, selftest_pytester, monkeypatch):
        """Control: with the bump defeated, the same reason IS ellipsized.

        Passing ``-o verbosity_test_cases=1`` makes ``getini`` return ``"1"``
        instead of ``"auto"``, so the plugin leaves the level alone. This proves
        the ``COLUMNS=80`` width is honored in-process and that truncation is
        reachable here — without it, ``test_skip_reason_shown_in_full_inline``
        could pass vacuously. If this control ever stops truncating, the positive
        test is no longer meaningful and CI should flag it.
        """
        monkeypatch.setenv("COLUMNS", "80")
        self._make_long_skip_test(selftest_pytester)
        result = selftest_pytester.runpytest(
            "--vip-config=vip.toml", "-v", "-o", "verbosity_test_cases=1"
        )
        result.assert_outcomes(skipped=1)
        collapsed = "".join(result.stdout.str().split())
        assert "...)" in collapsed
        assert "END_OF_REASON_SENTINEL" not in collapsed

    def test_skip_reason_not_forced_verbose_in_dot_mode(self, selftest_pytester):
        """Without ``-v`` the reporter stays in dot mode — the verbosity bump is
        gated on the user already having asked for per-test lines."""
        selftest_pytester.makepyfile(
            """
            import pytest

            @pytest.mark.skip(reason="some reason")
            def test_skips():
                pass
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml")
        result.assert_outcomes(skipped=1)
        result.stdout.no_fnmatch_line("*test_skips*SKIPPED*")

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

    def test_slow_marker_registered(self, selftest_pytester):
        result = selftest_pytester.runpytest("--markers")
        result.stdout.fnmatch_lines(["*slow: *"])

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

    def test_interactive_auth_skipped_when_no_auth_products(self, selftest_pytester):
        """--interactive-auth skips the browser flow when no auth-requiring products are enabled.

        When no products requiring authentication are configured, running with
        --interactive-auth should not error out; the auth flow should be skipped and
        tests should proceed normally.  See issue #173.
        """
        selftest_pytester.makepyfile(
            """
            def test_placeholder():
                assert True
            """
        )
        result = selftest_pytester.runpytest_subprocess(
            "--vip-config=vip.toml",
            "--interactive-auth",
            "-W",
            "always",
        )
        assert result.ret == 0
        result.assert_outcomes(passed=1)
        result.stderr.fnmatch_lines(
            ["*no auth-requiring products*skipping browser authentication*"]
        )

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

    def test_error_summary_preserves_line_breaks(self, selftest_pytester):
        """Multi-line exception messages retain newlines in failures.json error_summary."""
        selftest_pytester.makepyfile(
            """
            def test_multiline_error():
                raise RuntimeError("line one\\nline two\\nline three")
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
        assert "line one" in error_summary
        assert "line two" in error_summary
        assert "line three" in error_summary
        assert "\n" in error_summary, "error_summary must contain newlines for multi-line errors"

    def test_terminal_failed_line_stays_single_line(self, selftest_pytester):
        """Terminal FAILED summary line must not contain embedded newlines."""
        selftest_pytester.makepyfile(
            """
            def test_multiline_error():
                raise RuntimeError("line one\\nline two\\nline three")
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes(failed=1)
        failed_lines = [line for line in result.stdout.lines if "FAILED" in line]
        assert failed_lines, "expected at least one FAILED line in terminal output"
        assert "\n" not in failed_lines[0], "FAILED summary line must not contain embedded newlines"

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
        """Results JSON is populated when running with -n 2 (multi-worker)."""
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
            "2",
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

    def test_gw_worker_prefix_suppressed(self, selftest_pytester):
        """Under xdist with -v, the built-in ``[gw<N>]`` prefix should be hidden."""
        selftest_pytester.makepyfile(
            """
            def test_one():
                assert True

            def test_two():
                assert True
            """
        )
        result = selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            "-n",
            "2",
            "--dist",
            "loadgroup",
            "-v",
        )
        result.assert_outcomes(passed=2)
        for line in result.stdout.lines:
            assert not re.search(r"\[gw\d+\]", line), (
                f"Found xdist worker prefix in output line: {line!r}"
            )

    def test_no_auth_products_warning_not_duplicated_under_xdist(self, selftest_pytester):
        """The 'no auth-requiring products' skip warning fires once, not per worker.

        ``pytest_configure`` runs on the xdist controller *and* on every worker.
        The controller-only auth branch must not re-run on workers, or the skip
        warning floods the output once per worker (controller + N workers).
        """
        selftest_pytester.makepyfile(
            """
            def test_placeholder():
                assert True
            """
        )
        result = selftest_pytester.runpytest_subprocess(
            "--vip-config=vip.toml",
            "--interactive-auth",
            "-n",
            "2",
            "-W",
            "always",
        )
        assert result.ret == 0
        result.assert_outcomes(passed=1)
        combined = result.outlines + result.errlines
        hits = [line for line in combined if "skipping browser authentication" in line]
        assert len(hits) == 1, f"expected exactly one skip warning, got {len(hits)}: {hits}"

    def test_vip_metadata_survives_xdist(self, selftest_pytester):
        """Custom report attributes (markers, scenario fields) survive xdist transit."""
        # Use a plain test file and verify markers/scenario fields are present in results.
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
            "2",
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

    def test_verbose_xdist_output_is_one_line_per_test(self, selftest_pytester):
        """Under real parallel timing (-n 2 -v), each test gets one contiguous line.

        Sleeps force genuine overlap between workers so their events actually
        interleave on the controller (a fast no-op suite may finish one
        worker's test before the other's even starts, masking the bug).
        With the built-in TerminalReporter's non-xdist code path (entered
        because we delete ``report.node`` to hide ``[gw<N>]``), a test's
        location is written by ``pytest_runtest_logstart`` and its outcome by
        ``pytest_runtest_logreport`` as two separate writes. Those hooks fire
        from whichever worker event the controller processes next, so with
        real workers running concurrently the location line for one test can
        land, then another worker's events interleave, before that test's
        outcome line finally appears -- producing a location-only line with
        no PASSED/FAILED and a later, disconnected result line.
        """
        selftest_pytester.makepyfile(
            """
            import time

            def test_one():
                time.sleep(0.3)
                assert True

            def test_two():
                time.sleep(0.3)
                assert True

            def test_three():
                time.sleep(0.1)
                assert True

            def test_four():
                time.sleep(0.1)
                assert True
            """
        )
        result = selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            "-n",
            "2",
            "--dist",
            "loadgroup",
            "-v",
        )
        result.assert_outcomes(passed=4)

        test_line_pattern = re.compile(r"test_(one|two|three|four)")
        outcome_pattern = re.compile(r"PASSED|FAILED|ERROR|SKIPPED")
        bad_lines = [
            line
            for line in result.stdout.lines
            if test_line_pattern.search(line) and not outcome_pattern.search(line)
        ]
        assert not bad_lines, (
            f"Found location-only line(s) with no outcome on the same line: {bad_lines!r}"
        )


class TestHeadlessAuthOption:
    def test_headless_auth_option_registered(self, pytester):
        """The --headless-auth option should be registered by the plugin."""
        pytester.makeconftest("")
        result = pytester.runpytest("--help")
        result.stdout.fnmatch_lines(["*--headless-auth*"])


class TestHeadlessAuthFixture:
    def test_headless_auth_skipped_when_no_auth_products(self, pytester):
        """--headless-auth skips the browser flow when no auth-requiring products are enabled.

        If only Package Manager is enabled (or no products at all), --headless-auth
        should warn and continue rather than failing with UsageError -- see issue #173.
        """
        pytester.makefile(".toml", vip='[general]\ndeployment_name = "Selftest"')
        pytester.makepyfile(
            """
            def test_placeholder():
                assert True
            """
        )
        result = pytester.runpytest_subprocess(
            "--vip-config=vip.toml",
            "--headless-auth",
            "-W",
            "always",
        )
        assert result.ret == 0
        result.assert_outcomes(passed=1)
        result.stderr.fnmatch_lines(
            ["*no auth-requiring products*skipping browser authentication*"]
        )

    def test_headless_auth_skipped_when_only_package_manager_enabled(self, pytester):
        """--headless-auth skips auth when only Package Manager is enabled.

        Reproduces the scenario from issue #173: Connect/Workbench disabled,
        Package Manager enabled -- headless auth should be skipped.
        """
        pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n'
                "[connect]\nenabled = false\n"
                "[workbench]\nenabled = false\n"
                "[package_manager]\nenabled = true\n"
                'url = "https://pm.example.com"\n'
            ),
        )
        pytester.makepyfile(
            """
            def test_placeholder():
                assert True
            """
        )
        result = pytester.runpytest_subprocess(
            "--vip-config=vip.toml",
            "--headless-auth",
            "-W",
            "always",
        )
        assert result.ret == 0
        result.assert_outcomes(passed=1)
        result.stderr.fnmatch_lines(
            ["*no auth-requiring products*skipping browser authentication*"]
        )

    def test_interactive_auth_fixture_true_for_headless(self, pytester):
        """The interactive_auth fixture should return True when --headless-auth is active."""
        pytester.makeconftest(
            """
            import pytest
            from vip.plugin import _auth_session_key
            from vip.auth import InteractiveAuthSession
            from pathlib import Path

            @pytest.fixture(scope="session", autouse=True)
            def fake_auth_session(request):
                session = InteractiveAuthSession(
                    storage_state_path=Path("/dev/null"),
                )
                request.config.stash[_auth_session_key] = session

            @pytest.fixture(scope="session")
            def interactive_auth(request):
                session = request.config.stash.get(_auth_session_key, None)
                return session is not None
            """
        )
        pytester.makepyfile(
            """
            def test_fixture_value(interactive_auth):
                assert interactive_auth is True
            """
        )
        result = pytester.runpytest("-v")
        result.assert_outcomes(passed=1)

    def test_headless_auth_fixture_true_only_for_headless(self, pytester, monkeypatch):
        """The headless_auth fixture is True for --headless-auth, False otherwise."""
        # Patch the auth startup so the plugin doesn't launch a real browser.
        # monkeypatch auto-undoes after the test, so later tests see the real
        # functions (e.g. TestHeadlessAuthPluginWiring which asserts
        # AuthConfigError propagates).
        from pathlib import Path

        import vip.auth
        from vip.auth import InteractiveAuthSession

        def fake_start_auth(*args, **kwargs):
            return InteractiveAuthSession(storage_state_path=Path("/dev/null"))

        monkeypatch.setattr(vip.auth, "start_headless_auth", fake_start_auth)
        monkeypatch.setattr(vip.auth, "start_interactive_auth", fake_start_auth)

        # Mirror the real headless_auth fixture — pytester's tmp dir doesn't
        # auto-load src/vip_tests/conftest.py.
        pytester.makeconftest(
            """
            import pytest
            from vip.plugin import _auth_session_key

            @pytest.fixture(scope="session")
            def headless_auth(request):
                if not request.config.getoption("--headless-auth", default=False):
                    return False
                return request.config.stash.get(_auth_session_key, None) is not None
            """
        )
        pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n'
                '[connect]\nurl = "https://c.example.com"\n'
                '[auth]\nprovider = "password"\n'
            ),
        )
        pytester.makepyfile(
            """
            def test_fixture_value(request, headless_auth):
                expected = bool(request.config.getoption("--headless-auth", default=False))
                assert headless_auth is expected
            """
        )

        # --headless-auth: fixture is True.
        result = pytester.runpytest("-v", "--vip-config=vip.toml", "--headless-auth")
        result.assert_outcomes(passed=1)

        # --interactive-auth: session is populated but headless_auth is False.
        result = pytester.runpytest("-v", "--vip-config=vip.toml", "--interactive-auth")
        result.assert_outcomes(passed=1)

        # No auth flag: headless_auth is False.
        result = pytester.runpytest("-v", "--vip-config=vip.toml")
        result.assert_outcomes(passed=1)


class TestHeadlessAuthPluginWiring:
    """Verify that pytest_configure validates config for --headless-auth."""

    def test_headless_auth_requires_idp_for_oidc(self, pytester, monkeypatch):
        """--headless-auth with provider=oidc fails when idp is missing."""
        monkeypatch.setenv("VIP_TEST_USERNAME", "testuser")
        monkeypatch.setenv("VIP_TEST_PASSWORD", "testpass")
        pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n'
                '[connect]\nurl = "https://c.example.com"\n'
                '[auth]\nprovider = "oidc"\n'
            ),
        )
        pytester.makepyfile("def test_placeholder(): pass")
        result = pytester.runpytest("--vip-config=vip.toml", "--headless-auth")
        assert result.ret == pytest.ExitCode.USAGE_ERROR
        result.stderr.fnmatch_lines(["*--headless-auth*requires*idp*keycloak*okta*"])


class TestAuthModeStash:
    """The plugin stashes the active auth mode so tests can distinguish modes."""

    _FAKE_AUTH_CONFTEST = """
        import vip.auth
        from pathlib import Path
        from vip.auth import InteractiveAuthSession

        def _fake_session(*args, **kwargs):
            return InteractiveAuthSession(
                storage_state_path=Path("/dev/null"),
                api_key="fake-key",
            )

        vip.auth.start_interactive_auth = _fake_session
        vip.auth.start_headless_auth = _fake_session
        """

    def test_no_auth_option_leaves_mode_none(self, pytester):
        """With no auth option, auth_mode defaults to 'none'."""
        pytester.makefile(".toml", vip='[general]\ndeployment_name = "Selftest"')
        pytester.makepyfile(
            """
            from vip.plugin import _auth_mode_key

            def test_mode(request):
                assert request.config.stash.get(_auth_mode_key, "none") == "none"
            """
        )
        result = pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes(passed=1)

    def test_interactive_auth_sets_mode(self, pytester):
        """--interactive-auth sets _auth_mode_key to 'interactive'."""
        pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n'
                '[connect]\nurl = "https://c.example.com"\n'
            ),
        )
        pytester.makeconftest(self._FAKE_AUTH_CONFTEST)
        pytester.makepyfile(
            """
            from vip.plugin import _auth_mode_key

            def test_mode(request):
                assert request.config.stash.get(_auth_mode_key, None) == "interactive"
            """
        )
        result = pytester.runpytest("--vip-config=vip.toml", "--interactive-auth", "-v")
        result.assert_outcomes(passed=1)

    def test_headless_auth_sets_mode(self, pytester, monkeypatch):
        """--headless-auth sets _auth_mode_key to 'headless'."""
        monkeypatch.setenv("VIP_TEST_USERNAME", "testuser")
        monkeypatch.setenv("VIP_TEST_PASSWORD", "testpass")
        pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n'
                '[connect]\nurl = "https://c.example.com"\n'
                '[auth]\nprovider = "password"\n'
            ),
        )
        pytester.makeconftest(self._FAKE_AUTH_CONFTEST)
        pytester.makepyfile(
            """
            from vip.plugin import _auth_mode_key

            def test_mode(request):
                assert request.config.stash.get(_auth_mode_key, None) == "headless"
            """
        )
        result = pytester.runpytest("--vip-config=vip.toml", "--headless-auth", "-v")
        result.assert_outcomes(passed=1)

    @pytest.mark.parametrize(
        ("auth_flag", "expected_mode"),
        [("--interactive-auth", "interactive"), ("--headless-auth", "headless")],
    )
    def test_auth_mode_forwarded_to_xdist_workers(
        self, pytester, monkeypatch, auth_flag, expected_mode
    ):
        """Controller forwards vip_auth_mode via workerinput; workers restore it.

        Each test records ``workerid`` into a shared marker dir; we then assert
        that *both* xdist workers actually executed tests (not just that every
        test saw the restored mode). With only 2 tests the load scheduler can
        assign both to one worker, so we parametrize 8 tests and check the
        distinct-workerid set.
        """
        monkeypatch.setenv("VIP_TEST_USERNAME", "testuser")
        monkeypatch.setenv("VIP_TEST_PASSWORD", "testpass")
        pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n'
                '[connect]\nurl = "https://c.example.com"\n'
                '[auth]\nprovider = "password"\n'
            ),
        )
        marker_dir = pytester.path / "worker_markers"
        marker_dir.mkdir()
        pytester.makeconftest(self._FAKE_AUTH_CONFTEST)
        pytester.makepyfile(
            f"""
            import pytest
            from vip.plugin import _auth_mode_key

            MARKER_DIR = {str(marker_dir)!r}

            @pytest.mark.parametrize("i", list(range(8)))
            def test_worker_mode(request, i):
                assert hasattr(request.config, "workerinput"), "expected xdist worker"
                assert request.config.stash[_auth_mode_key] == {expected_mode!r}
                workerid = request.config.workerinput["workerid"]
                open(f"{{MARKER_DIR}}/{{workerid}}", "a").close()
            """
        )
        result = pytester.runpytest("--vip-config=vip.toml", auth_flag, "-n", "2", "-v")
        result.assert_outcomes(passed=8)
        workerids = {p.name for p in marker_dir.iterdir()}
        assert len(workerids) == 2, (
            f"expected both xdist workers to restore mode, got workerids={workerids}"
        )

    @pytest.mark.parametrize(
        ("auth_flag", "expected_mode"),
        [("--interactive-auth", "interactive"), ("--headless-auth", "headless")],
    )
    def test_auth_mode_forwarded_to_workers_without_auth_session(
        self, pytester, auth_flag, expected_mode
    ):
        """auth_mode stays consistent on workers when no auth product is configured.

        With only a non-auth product (Package Manager) the controller sets the
        auth mode but never establishes a browser session, so the session path
        forwards nothing. Workers must still mirror the controller's mode, or
        the ``auth_mode`` fixture diverges between xdist and non-xdist runs.
        """
        pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n'
                '[package_manager]\nurl = "https://p3m.example.com"\n'
            ),
        )
        marker_dir = pytester.path / "worker_markers"
        marker_dir.mkdir()
        pytester.makepyfile(
            f"""
            import pytest
            from vip.plugin import _auth_mode_key

            MARKER_DIR = {str(marker_dir)!r}

            @pytest.mark.parametrize("i", list(range(8)))
            def test_worker_mode(request, i):
                assert hasattr(request.config, "workerinput"), "expected xdist worker"
                assert request.config.stash.get(_auth_mode_key, "none") == {expected_mode!r}
                workerid = request.config.workerinput["workerid"]
                open(f"{{MARKER_DIR}}/{{workerid}}", "a").close()
            """
        )
        result = pytester.runpytest("--vip-config=vip.toml", auth_flag, "-n", "2", "-v")
        result.assert_outcomes(passed=8)
        workerids = {p.name for p in marker_dir.iterdir()}
        assert len(workerids) == 2, (
            f"expected both xdist workers to restore mode, got workerids={workerids}"
        )


class TestRestoreWorkerAuth:
    """``_restore_worker_auth`` recreates the controller's auth state on each
    xdist worker.  When the controller rewrote ``connect.url`` (split sub-path
    dashboard + root API), workers must pick up the corrected URL or their
    ``ConnectClient`` will 404 against the original sub-path."""

    @staticmethod
    def _config(**worker_inputs):
        """Stub a pytest.Config with the given xdist ``workerinput`` dict."""
        from unittest.mock import MagicMock

        cfg = MagicMock()
        cfg.workerinput = worker_inputs
        cfg.stash = {}
        return cfg

    def test_rewritten_connect_url_propagates_to_vip_cfg(self):
        from vip.config import ConnectConfig, VIPConfig
        from vip.plugin import _restore_worker_auth

        vip_cfg = VIPConfig()
        vip_cfg.connect = ConnectConfig(enabled=True, url="https://c.example.com/connect")
        cfg = self._config(
            vip_api_key="K",
            vip_connect_url="https://c.example.com",
            vip_storage_state="/tmp/state.json",
            vip_key_name="_vip_interactive_1",
        )

        _restore_worker_auth(cfg, vip_cfg)

        assert vip_cfg.connect.url == "https://c.example.com"
        assert vip_cfg.connect.api_key == "K"

    def test_matching_connect_url_is_noop(self):
        """No rewrite case: controller passed the same URL; leave it alone."""
        from vip.config import ConnectConfig, VIPConfig
        from vip.plugin import _restore_worker_auth

        vip_cfg = VIPConfig()
        vip_cfg.connect = ConnectConfig(enabled=True, url="https://c.example.com")
        cfg = self._config(
            vip_api_key="K",
            vip_connect_url="https://c.example.com",
        )

        _restore_worker_auth(cfg, vip_cfg)

        assert vip_cfg.connect.url == "https://c.example.com"

    def test_empty_connect_url_keeps_existing(self):
        """Controller had no Connect URL to share — don't blank out the
        worker's existing value."""
        from vip.config import ConnectConfig, VIPConfig
        from vip.plugin import _restore_worker_auth

        vip_cfg = VIPConfig()
        vip_cfg.connect = ConnectConfig(enabled=True, url="https://c.example.com")
        cfg = self._config(vip_api_key="K", vip_connect_url="")

        _restore_worker_auth(cfg, vip_cfg)

        assert vip_cfg.connect.url == "https://c.example.com"

    def test_connect_disabled_keeps_existing(self):
        """Workbench-only run: Connect is disabled.  Even if a stray
        ``vip_connect_url`` shows up in workerinput, don't enable Connect
        by accident."""
        from vip.config import ConnectConfig, VIPConfig
        from vip.plugin import _restore_worker_auth

        vip_cfg = VIPConfig()
        vip_cfg.connect = ConnectConfig(enabled=False, url="")
        cfg = self._config(vip_connect_url="https://c.example.com")

        _restore_worker_auth(cfg, vip_cfg)

        assert vip_cfg.connect.url == ""


class TestHeartbeat:
    """Unit tests for the long-running test heartbeat."""

    def test_heartbeat_fires(self):
        from vip.plugin import _Heartbeat

        output: list[str] = []
        hb = _Heartbeat(output.append, interval=0.2)
        hb.start()
        time.sleep(0.7)
        hb.stop()
        assert len(output) >= 2
        assert "still running" in output[0]

    def test_heartbeat_stop_is_immediate(self):
        from vip.plugin import _Heartbeat

        output: list[str] = []
        hb = _Heartbeat(output.append, interval=10)
        hb.start()
        hb.stop()
        assert len(output) == 0

    def test_heartbeat_shows_elapsed_seconds(self):
        from vip.plugin import _Heartbeat

        output: list[str] = []
        hb = _Heartbeat(output.append, interval=0.2)
        hb.start()
        time.sleep(0.5)
        hb.stop()
        assert len(output) >= 1
        # Should contain a number of seconds in parentheses
        assert re.search(r"\(\d+s\)", output[0])


class TestRequireConnectApiKey:
    """Unit tests for ``require_connect_api_key``.

    The fixture's job is to convert "auth setup failed silently → cascading
    401s deep in scenario steps" into a single root-cause failure visible at
    the top of the failure section.
    """

    def _config(self, *, url: str = "", api_key: str = "", enabled: bool = True):
        from vip.config import ConnectConfig, VIPConfig

        cfg = VIPConfig()
        cfg.connect = ConnectConfig(url=url, enabled=enabled, api_key=api_key)
        return cfg

    def test_no_op_when_connect_not_configured(self):
        """No URL → fixture returns None upstream; helper must not fail."""
        from vip.plugin import require_connect_api_key

        require_connect_api_key(self._config())  # no raise

    def test_no_op_when_connect_disabled(self):
        from vip.plugin import require_connect_api_key

        cfg = self._config(url="https://c.example.com", api_key="", enabled=False)
        require_connect_api_key(cfg)  # no raise — disabled treats as unconfigured

    def test_no_op_when_api_key_present(self):
        from vip.plugin import require_connect_api_key

        cfg = self._config(url="https://c.example.com", api_key="abc123")
        require_connect_api_key(cfg)  # no raise

    def test_fails_with_actionable_message_when_key_missing(self):
        from vip.plugin import require_connect_api_key

        cfg = self._config(url="https://c.example.com", api_key="")
        with pytest.raises(pytest.fail.Exception) as exc_info:
            require_connect_api_key(cfg)
        msg = str(exc_info.value)
        # Mentions each remediation path so the user knows what to try.
        assert "VIP_CONNECT_API_KEY" in msg
        assert "vip.toml" in msg
        assert "--headless-auth" in msg
        # Points back at the upstream mint diagnostic for the headless case.
        assert "Mint diagnostic" in msg


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
