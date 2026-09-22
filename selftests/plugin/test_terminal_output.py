"""Tests for vip.plugin module — terminal output and skip-reason rendering."""

from __future__ import annotations

import json
import re


class TestPluginIntegration:
    """Integration tests using pytester to exercise the plugin end-to-end.

    pytester runs pytest in a subprocess, so each invocation gets its own
    plugin state (including a fresh ``_results`` list).
    """

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
        gated on the user already having asked for per-test lines.
        """
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
