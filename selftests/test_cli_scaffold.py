"""Tests for the ``vip scaffold`` subcommand (run_scaffold in vip.cli)."""

from __future__ import annotations

import argparse
import subprocess
import sys


def _make_args(**overrides) -> argparse.Namespace:
    """Build a minimal args namespace for run_scaffold."""
    defaults = {
        "output": "./custom_tests",
        "force": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestScaffoldList:
    """``--list`` enumerates templates and exits without writing anything."""

    def test_list_does_not_write_output_dir(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "should_not_exist"
        run_scaffold(_make_args(list=True, output=str(dest)))

        assert not dest.exists()

    def test_list_names_both_templates(self, capsys):
        from vip.cli import run_scaffold

        run_scaffold(_make_args(list=True))

        out = capsys.readouterr().out
        assert "minimal" in out
        assert "cross-product" in out

    def test_list_via_cli_exits_zero_without_output_flag(self):
        result = subprocess.run(
            [sys.executable, "-m", "vip.cli", "scaffold", "--list"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "minimal" in result.stdout
        assert "cross-product" in result.stdout


class TestScaffoldTemplateSelection:
    """``--template`` selects between the registered scaffold templates."""

    def test_default_template_is_cross_product(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "default_tests"
        run_scaffold(_make_args(output=str(dest)))

        assert (dest / "test_gxp_validation.feature").is_file()
        assert not (dest / "test_custom_check.feature").exists()

    def test_minimal_template_scaffolds_expected_files(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "minimal_tests"
        run_scaffold(_make_args(output=str(dest), template="minimal"))

        assert (dest / "test_custom_check.feature").is_file()
        assert (dest / "test_custom_check.py").is_file()
        assert (dest / "conftest.py").is_file()
        assert (dest / "README.md").is_file()
        assert (dest / "AGENTS.md").is_file()

    def test_cross_product_template_includes_agents_md(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "cross_tests"
        run_scaffold(_make_args(output=str(dest), template="cross-product"))

        assert (dest / "test_gxp_validation.feature").is_file()
        assert (dest / "AGENTS.md").is_file()

    def test_unknown_template_exits_nonzero_and_lists_valid_names(self, tmp_path, capsys):
        import pytest

        from vip.cli import run_scaffold

        dest = tmp_path / "bad_tests"
        with pytest.raises(SystemExit) as exc_info:
            run_scaffold(_make_args(output=str(dest), template="bogus"))

        assert exc_info.value.code != 0
        err = capsys.readouterr().err
        assert "bogus" in err
        assert "minimal" in err
        assert "cross-product" in err
        assert not dest.exists()


class TestMinimalTemplateContract:
    """Pins the two defects fixed in issue #608 so they can't silently regress."""

    def test_minimal_step_file_has_product_marker(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "minimal_marker_tests"
        run_scaffold(_make_args(output=str(dest), template="minimal"))

        step_text = (dest / "test_custom_check.py").read_text()
        assert "pytest.mark.connect" in step_text

    def test_minimal_template_does_not_hardcode_example_dot_com(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "minimal_no_internet_tests"
        run_scaffold(_make_args(output=str(dest), template="minimal"))

        step_text = (dest / "test_custom_check.py").read_text()
        assert "example.com" not in step_text


class TestScaffoldCreatesExpectedFiles:
    """run_scaffold copies the expected files to the output directory."""

    def test_scaffold_creates_feature_file(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "my_tests"
        run_scaffold(_make_args(output=str(dest)))

        assert (dest / "test_gxp_validation.feature").is_file()

    def test_scaffold_creates_step_definitions(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "my_tests"
        run_scaffold(_make_args(output=str(dest)))

        assert (dest / "test_gxp_validation.py").is_file()

    def test_scaffold_creates_conftest(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "my_tests"
        run_scaffold(_make_args(output=str(dest)))

        assert (dest / "conftest.py").is_file()

    def test_scaffold_creates_readme(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "my_tests"
        run_scaffold(_make_args(output=str(dest)))

        assert (dest / "README.md").is_file()


class TestScaffoldFileContent:
    """Scaffolded files have the expected content for auto-skip and VIP patterns."""

    def test_feature_file_has_connect_workbench_tags(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "my_tests"
        run_scaffold(_make_args(output=str(dest)))

        feature_text = (dest / "test_gxp_validation.feature").read_text()
        assert "@connect" in feature_text
        assert "@workbench" in feature_text

    def test_step_file_imports_pytest_bdd(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "my_tests"
        run_scaffold(_make_args(output=str(dest)))

        step_text = (dest / "test_gxp_validation.py").read_text()
        assert "from pytest_bdd import" in step_text

    def test_step_file_has_pytest_mark_connect(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "my_tests"
        run_scaffold(_make_args(output=str(dest)))

        step_text = (dest / "test_gxp_validation.py").read_text()
        assert "pytest.mark.connect" in step_text

    def test_step_file_has_pytest_mark_workbench(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "my_tests"
        run_scaffold(_make_args(output=str(dest)))

        step_text = (dest / "test_gxp_validation.py").read_text()
        assert "pytest.mark.workbench" in step_text

    def test_conftest_defines_check_packages(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "my_tests"
        run_scaffold(_make_args(output=str(dest)))

        conftest_text = (dest / "conftest.py").read_text()
        assert "check_packages" in conftest_text

    def test_conftest_does_not_shadow_expected_r_versions(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "my_tests"
        run_scaffold(_make_args(output=str(dest)))

        conftest_text = (dest / "conftest.py").read_text()
        # Must NOT redefine these — they are provided by VIP core conftest
        assert "def expected_r_versions" not in conftest_text
        assert "def expected_python_versions" not in conftest_text


class TestScaffoldOverwriteBehavior:
    """Overwrite behavior: --force flag controls whether existing dest is replaced."""

    def test_scaffold_fails_if_dest_exists_without_force(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "my_tests"
        dest.mkdir()
        (dest / "existing.txt").write_text("keep me")

        import pytest

        with pytest.raises(SystemExit):
            run_scaffold(_make_args(output=str(dest), force=False))

        # Original file should still be present (not clobbered)
        assert (dest / "existing.txt").is_file()

    def test_scaffold_overwrites_with_force(self, tmp_path):
        from vip.cli import run_scaffold

        dest = tmp_path / "my_tests"
        dest.mkdir()
        (dest / "stale.txt").write_text("old content")

        run_scaffold(_make_args(output=str(dest), force=True))

        # Stale file should be gone; scaffold files present
        assert not (dest / "stale.txt").exists()
        assert (dest / "test_gxp_validation.feature").is_file()


class TestScaffoldCLI:
    """``vip scaffold`` appears in the CLI help and produces a valid output."""

    def test_scaffold_in_cli_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "vip.cli", "--help"],
            capture_output=True,
            text=True,
        )
        assert "scaffold" in result.stdout

    def test_scaffold_subcommand_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "vip.cli", "scaffold", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--output" in result.stdout


class TestScaffoldExcludesBuildArtifacts:
    """A scaffolded directory must not carry the source checkout's detritus."""

    def test_no_pycache_in_scaffolded_output(self, tmp_path):
        """A checkout that has run the examples must not leak __pycache__.

        Running the bundled examples locally leaves __pycache__ beside them, and
        copytree without an ignore= copied it straight into the customer's brand
        new extension directory -- making the scaffold output depend on whether
        the VIP checkout happened to have run its own tests.
        """
        from vip.cli import run_scaffold

        dest = tmp_path / "scaffolded"
        run_scaffold(_make_args(template="21cfr-part11-validation", output=str(dest)))

        leaked = [p for p in dest.rglob("*") if p.name == "__pycache__" or p.suffix == ".pyc"]
        assert leaked == [], f"scaffold leaked build artifacts: {leaked}"

    def test_scaffold_still_copies_the_real_files(self, tmp_path):
        """Guard the ignore pattern against over-matching."""
        from vip.cli import run_scaffold

        dest = tmp_path / "scaffolded"
        run_scaffold(_make_args(template="21cfr-part11-validation", output=str(dest)))

        for name in (
            "README.md",
            "conftest.py",
            "controls.toml",
            "test_21CFR_part11_validation.feature",
            "test_21CFR_part11_validation.py",
        ):
            assert (dest / name).is_file(), f"{name} missing from scaffold output"
