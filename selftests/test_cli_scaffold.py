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
