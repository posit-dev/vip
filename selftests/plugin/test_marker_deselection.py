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

    def test_bdd_requires_tag_deselected(self, selftest_pytester):
        """A scenario tagged ``@requires_connect`` is deselected, not skipped,
        when Connect is not configured.
        """
        selftest_pytester.makefile(
            ".feature",
            test_perf=(
                "@performance\n"
                "Feature: Perf test\n"
                "  @requires_connect\n"
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
        assert "SKIPPED" not in result.stdout.str()

    def test_bdd_feature_level_requires_tag_deselected(self, selftest_pytester):
        """A ``@requires_*`` tag on the Feature applies to every scenario in it."""
        selftest_pytester.makefile(
            ".feature",
            test_feat=(
                "@requires_package_manager\n"
                "Feature: PM checks\n"
                "  Scenario: First\n"
                "    Then it passes\n"
                "  Scenario: Second\n"
                "    Then it passes\n"
            ),
        )
        selftest_pytester.makepyfile(
            test_feat="""
            from pytest_bdd import scenarios, then

            scenarios("test_feat.feature")

            @then("it passes")
            def it_passes():
                pass
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes()
        result.stdout.fnmatch_lines(["*2 deselected*"])

    def test_bdd_requires_tag_runs_when_configured(self, selftest_pytester):
        """A ``@requires_connect`` scenario runs when Connect IS configured."""
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
                "  @requires_connect\n"
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

    def test_bdd_untagged_given_guard_skips_not_deselects(self, selftest_pytester):
        """Without a ``@requires_*`` tag the Given guard alone does not deselect;
        the scenario is collected and skipped at runtime by the step itself.
        """
        selftest_pytester.makefile(
            ".feature",
            test_untagged=(
                "Feature: Untagged\n"
                "  Scenario: Guarded only by a Given step\n"
                "    Given Connect is configured in vip.toml\n"
            ),
        )
        selftest_pytester.makepyfile(
            test_untagged="""
            import pytest
            from pytest_bdd import scenario, given

            @scenario("test_untagged.feature", "Guarded only by a Given step")
            def test_guarded():
                pass

            @given("Connect is configured in vip.toml")
            def connect_configured():
                pytest.skip("Connect is not configured")
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes(skipped=1)
        result.stdout.fnmatch_lines(
            ["*VIP: *test_guarded* has a product Given step but no @requires_connect tag*"]
        )

    def test_bdd_untagged_background_guard_warns(self, selftest_pytester):
        """A product Given step in a Background counts: pytest-bdd runs it in every scenario."""
        selftest_pytester.makefile(
            ".feature",
            test_bg=(
                "Feature: Background guard\n"
                "  Background:\n"
                "    Given Workbench is configured with a custom image\n"
                "  Scenario: Uses the image\n"
                "    Then it passes\n"
            ),
        )
        selftest_pytester.makepyfile(
            test_bg="""
            from pytest_bdd import scenarios, given, then

            scenarios("test_bg.feature")

            @given("Workbench is configured with a custom image")
            def custom_image():
                pass

            @then("it passes")
            def it_passes():
                pass
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes(passed=1)
        result.stdout.fnmatch_lines(
            ["*VIP: *test_uses_the_image* has a product Given step but no @requires_workbench*"]
        )

    def test_bdd_tagged_guard_does_not_warn(self, selftest_pytester):
        """A product marker satisfies the guard as well as a ``@requires_*`` tag."""
        selftest_pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n[connect]\nurl = "https://example.com"\n'
            ),
        )
        selftest_pytester.makefile(
            ".feature",
            test_tagged=(
                "@connect\n"
                "Feature: Tagged\n"
                "  Scenario: Guarded and tagged\n"
                "    Given Connect is configured in vip.toml\n"
            ),
        )
        selftest_pytester.makepyfile(
            test_tagged="""
            from pytest_bdd import scenarios, given

            scenarios("test_tagged.feature")

            @given("Connect is configured in vip.toml")
            def connect_configured():
                pass
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes(passed=1)
        assert "has a product Given step" not in result.stdout.str()

    def test_bdd_outline_row_guard_warns_only_for_untagged_rows(self, selftest_pytester):
        """``<product> is configured`` resolves per Examples row before checking tags."""
        selftest_pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n[connect]\nurl = "https://example.com"\n'
                '[workbench]\nurl = "https://example.com"\n'
            ),
        )
        selftest_pytester.makefile(
            ".feature",
            test_rows=(
                "Feature: Rows\n"
                "  Scenario Outline: <product> check\n"
                "    Given <product> is configured in vip.toml\n"
                "\n"
                "    @requires_connect\n"
                "    Examples:\n"
                "      | product |\n"
                "      | Connect |\n"
                "\n"
                "    Examples:\n"
                "      | product   |\n"
                "      | Workbench |\n"
            ),
        )
        selftest_pytester.makepyfile(
            test_rows="""
            from pytest_bdd import scenarios, given, parsers

            scenarios("test_rows.feature")

            @given(parsers.parse("{product} is configured in vip.toml"))
            def product_configured(product):
                pass
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes(passed=2)
        out = result.stdout.str()
        assert out.count("has a product Given step") == 1
        assert "no @requires_workbench tag" in out

    _UNTAGGED_OUTLINE = (
        "Feature: Untagged outline\n"
        "  Scenario Outline: Page <page>\n"
        "    Given Connect is configured in vip.toml\n"
        "\n"
        "    Examples:\n"
        "      | page |\n"
        "      | a    |\n"
        "      | b    |\n"
        "      | c    |\n"
        "\n"
        "  Scenario: Plain\n"
        "    Given Connect is configured in vip.toml\n"
    )

    _UNTAGGED_STEPS = """
        import pytest
        from pytest_bdd import scenarios, given

        scenarios("test_outline.feature")

        @given("Connect is configured in vip.toml")
        def connect_configured():
            pytest.skip("Connect is not configured")
        """

    def test_bdd_untagged_outline_warns_once_per_scenario(self, selftest_pytester):
        """An outline's rows share one warning, which points at the Examples block."""
        selftest_pytester.makefile(".feature", test_outline=self._UNTAGGED_OUTLINE)
        selftest_pytester.makepyfile(test_outline=self._UNTAGGED_STEPS)
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes(skipped=4)
        out = result.stdout.str()
        assert out.count("has a product Given step") == 2
        assert "or to the Examples block holding those rows" in out

    def test_bdd_guard_warning_not_repeated_per_xdist_worker(self, selftest_pytester):
        """Every xdist worker collects every item; only one of them warns."""
        selftest_pytester.makefile(".feature", test_outline=self._UNTAGGED_OUTLINE)
        selftest_pytester.makepyfile(test_outline=self._UNTAGGED_STEPS)
        serial = selftest_pytester.runpytest("--vip-config=vip.toml", "-p", "no:randomly")
        parallel = selftest_pytester.runpytest("--vip-config=vip.toml", "-n", "2")
        assert serial.parseoutcomes()["warnings"] == 2
        assert parallel.parseoutcomes()["warnings"] == 2

    def test_bdd_guard_check_survives_private_api_change(self, selftest_pytester, monkeypatch):
        """If pytest-bdd's private template API changes shape, collection still succeeds."""
        from pytest_bdd.parser import ScenarioTemplate

        def _broken(self, context):
            raise AttributeError("render moved")

        # monkeypatch, not a conftest: the run is in-process, so the patch must be undone after.
        monkeypatch.setattr(ScenarioTemplate, "render", _broken)
        selftest_pytester.makefile(".feature", test_outline=self._UNTAGGED_OUTLINE)
        selftest_pytester.makepyfile(test_outline=self._UNTAGGED_STEPS)
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "--collect-only", "-q")
        assert result.ret == 0
        result.stdout.fnmatch_lines(["*4 tests collected*"])

    def test_bdd_tagged_examples_deselected_per_product(self, selftest_pytester):
        """Tags on an ``Examples:`` block deselect only that block's rows."""
        selftest_pytester.makefile(
            ".feature",
            test_param=(
                "@performance\n"
                "Feature: Param test\n"
                "  Scenario Outline: <product> check\n"
                "    Given <product> is configured in vip.toml\n"
                "    Then it passes\n"
                "\n"
                "    @requires_connect\n"
                "    Examples:\n"
                "      | product |\n"
                "      | Connect |\n"
                "\n"
                "    Examples:\n"
                "      | product   |\n"
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
        # Connect rows are tagged and Connect is not configured: deselected.
        # CustomApp rows carry no tag: collected, then skipped by the step.
        result.stdout.fnmatch_lines(["*1 deselected*"])
        result.assert_outcomes(skipped=1)

    def test_bdd_requires_tag_kept_under_no_auth(self, selftest_pytester):
        """``--no-auth`` keeps a ``@requires_connect`` scenario: the tag means
        Connect is configured, not that the scenario needs credentials.
        """
        selftest_pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n[connect]\nurl = "https://example.com"\n'
            ),
        )
        selftest_pytester.makefile(
            ".feature",
            test_auth=(
                "Feature: Auth\n"
                "  @requires_connect\n"
                "  Scenario: Needs Connect\n"
                "    Then it passes\n"
            ),
        )
        selftest_pytester.makepyfile(
            test_auth="""
            from pytest_bdd import scenarios, then

            scenarios("test_auth.feature")

            @then("it passes")
            def it_passes():
                pass
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "--no-auth", "-v")
        result.assert_outcomes(passed=1)

    def test_bdd_multiple_requires_tags_need_every_product(self, selftest_pytester):
        """With two ``@requires_*`` tags, one unconfigured product is enough to deselect."""
        selftest_pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n[connect]\nurl = "https://example.com"\n'
            ),
        )
        selftest_pytester.makefile(
            ".feature",
            test_both=(
                "Feature: Both\n"
                "  @requires_connect @requires_package_manager\n"
                "  Scenario: Needs both\n"
                "    Then it passes\n"
                "  @requires_connect\n"
                "  Scenario: Needs Connect\n"
                "    Then it passes\n"
            ),
        )
        selftest_pytester.makepyfile(
            test_both="""
            from pytest_bdd import scenarios, then

            scenarios("test_both.feature")

            @then("it passes")
            def it_passes():
                pass
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml", "-v")
        result.assert_outcomes(passed=1)
        result.stdout.fnmatch_lines(["*test_needs_connect PASSED*", "*1 deselected*"])

    def test_auth_modes_select_by_marker(self, selftest_pytester):
        """``--api-auth`` keeps ``@requires_*`` and ``@connect @api_auth`` scenarios and drops plain
        ``@connect``; ``--no-auth`` keeps only the ``@requires_*`` one.
        """
        selftest_pytester.makefile(
            ".toml",
            vip=(
                '[general]\ndeployment_name = "Selftest"\n[connect]\nurl = "https://example.com"\n'
            ),
        )
        selftest_pytester.makefile(
            ".feature",
            test_modes=(
                "Feature: Modes\n"
                "  @requires_connect\n"
                "  Scenario: Configured only\n"
                "    Then it passes\n"
                "  @connect @api_auth\n"
                "  Scenario: API key only\n"
                "    Then it passes\n"
                "  @connect\n"
                "  Scenario: Browser login\n"
                "    Then it passes\n"
            ),
        )
        selftest_pytester.makepyfile(
            test_modes="""
            from pytest_bdd import scenarios, then

            scenarios("test_modes.feature")

            @then("it passes")
            def it_passes():
                pass
            """
        )
        api = selftest_pytester.runpytest("--vip-config=vip.toml", "--api-auth", "-v")
        api.assert_outcomes(passed=2)
        api.stdout.fnmatch_lines(["*1 deselected*"])
        assert "test_browser_login" not in api.stdout.str()

        no_auth = selftest_pytester.runpytest("--vip-config=vip.toml", "--no-auth", "-v")
        no_auth.assert_outcomes(passed=1)
        no_auth.stdout.fnmatch_lines(["*test_configured_only PASSED*", "*2 deselected*"])

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
        (ext_dir / "test_extra.py").write_text(
            "def test_from_extension():\n    assert True\n", encoding="utf-8"
        )

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
                "*requires_connect:*",
                "*requires_workbench:*",
                "*requires_package_manager:*",
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
