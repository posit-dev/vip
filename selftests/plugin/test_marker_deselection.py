"""Tests for vip.plugin module — marker, option, and deselection wiring."""

from __future__ import annotations


class TestPluginIntegration:
    """Integration tests using pytester to exercise the plugin end-to-end.

    pytester runs pytest in a subprocess, so each invocation gets its own
    plugin state (including a fresh ``_results`` list).
    """

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
        should be deselected (not skipped) when Connect is not configured.
        """
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
        when Connect IS configured.
        """
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
        when the product is not configured.
        """
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
