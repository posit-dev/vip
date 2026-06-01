"""Tests for Workbench runtime version verification feature."""

from __future__ import annotations

import textwrap

import pytest

from vip.config import RuntimesConfig, VIPConfig, load_config
from vip_tests.workbench.pages.homepage import NewSessionDialog


class TestRuntimesConfigExcluded:
    def test_defaults_to_empty_excluded_lists(self):
        rc = RuntimesConfig()
        assert rc.r_excluded_versions == []
        assert rc.python_excluded_versions == []

    def test_accepts_excluded_versions(self):
        rc = RuntimesConfig(
            r_versions=["4.3.1", "4.4.0"],
            python_versions=["3.11.0"],
            r_excluded_versions=["3.6.3"],
            python_excluded_versions=["2.7.18"],
        )
        assert rc.r_excluded_versions == ["3.6.3"]
        assert rc.python_excluded_versions == ["2.7.18"]

    def test_load_config_reads_excluded_versions(self, tmp_path):
        cfg_file = tmp_path / "vip.toml"
        cfg_file.write_text(
            textwrap.dedent("""\
                [runtimes]
                r_versions = ["4.3.1", "4.4.0"]
                python_versions = ["3.11.0"]
                r_excluded_versions = ["3.6.3", "3.5.0"]
                python_excluded_versions = ["2.7.18"]
            """)
        )
        config = load_config(cfg_file)
        assert config.runtimes.r_versions == ["4.3.1", "4.4.0"]
        assert config.runtimes.python_versions == ["3.11.0"]
        assert config.runtimes.r_excluded_versions == ["3.6.3", "3.5.0"]
        assert config.runtimes.python_excluded_versions == ["2.7.18"]

    def test_load_config_excluded_default_empty(self, tmp_path):
        cfg_file = tmp_path / "vip.toml"
        cfg_file.write_text(
            textwrap.dedent("""\
                [runtimes]
                r_versions = ["4.3.1"]
            """)
        )
        config = load_config(cfg_file)
        assert config.runtimes.r_excluded_versions == []
        assert config.runtimes.python_excluded_versions == []

    def test_vip_config_default_runtimes_excluded_empty(self):
        config = VIPConfig()
        assert config.runtimes.r_excluded_versions == []
        assert config.runtimes.python_excluded_versions == []


class TestNewSessionDialogVersionSelectors:
    def test_r_version_dropdown_selector_defined(self):
        assert hasattr(NewSessionDialog, "R_VERSION_DROPDOWN")
        assert NewSessionDialog.R_VERSION_DROPDOWN

    def test_python_version_dropdown_selector_defined(self):
        assert hasattr(NewSessionDialog, "PYTHON_VERSION_DROPDOWN")
        assert NewSessionDialog.PYTHON_VERSION_DROPDOWN

    def test_r_version_selector_is_css_id(self):
        assert NewSessionDialog.R_VERSION_DROPDOWN.startswith("#")

    def test_python_version_selector_is_css_id(self):
        assert NewSessionDialog.PYTHON_VERSION_DROPDOWN.startswith("#")


class TestRuntimeVersionsFeatureFile:
    @pytest.fixture
    def feature_path(self):
        from pathlib import Path

        return (
            Path(__file__).parent.parent
            / "src"
            / "vip_tests"
            / "workbench"
            / "test_runtime_versions.feature"
        )

    def test_feature_file_exists(self, feature_path):
        assert feature_path.exists(), f"Feature file not found: {feature_path}"

    def test_feature_has_workbench_tag(self, feature_path):
        content = feature_path.read_text()
        assert "@workbench" in content

    def test_feature_has_three_scenarios(self, feature_path):
        from vip.gherkin import parse_feature_file

        result = parse_feature_file(feature_path)
        assert len(result["scenarios"]) == 3

    def test_feature_scenarios_cover_r_python_and_session(self, feature_path):
        from vip.gherkin import parse_feature_file

        result = parse_feature_file(feature_path)
        titles = [s["title"] for s in result["scenarios"]]
        assert any("R version" in t for t in titles)
        assert any("Python version" in t for t in titles)
        assert any("RStudio" in t or "session" in t.lower() for t in titles)
