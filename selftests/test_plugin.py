"""Tests for vip.plugin module."""

from __future__ import annotations

import json

import pytest

from vip.plugin import _version_tuple


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

    def test_unconfigured_product_skips(self, selftest_pytester):
        selftest_pytester.makepyfile(
            """
            import pytest

            @pytest.mark.connect
            def test_needs_connect():
                assert True
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-rs")
        result.stdout.fnmatch_lines(["*SKIPPED*not configured*"])

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

    def test_interactive_auth_requires_connect_url(self, selftest_pytester):
        """--interactive-auth fails fast when Connect URL is not configured."""
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
        result.stderr.fnmatch_lines(["*--interactive-auth requires Connect URL*"])
