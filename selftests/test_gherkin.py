"""Tests for vip.gherkin module."""

from __future__ import annotations

from vip.gherkin import parse_feature_file


class TestParseFeatureFile:
    def test_basic_feature(self, tmp_path):
        f = tmp_path / "test_basic.feature"
        f.write_text(
            "@connect\n"
            "Feature: Connect authentication\n"
            "  As a Posit Team administrator\n"
            "  I want to verify Connect auth\n"
            "\n"
            "  Scenario: User can log in\n"
            "    Given Connect is accessible\n"
            "    When a user enters credentials\n"
            "    Then the user is authenticated\n"
        )
        result = parse_feature_file(f)
        assert result["title"] == "Connect authentication"
        assert result["marker"] == "connect"
        assert "Posit Team administrator" in result["description"]
        assert len(result["scenarios"]) == 1
        assert result["scenarios"][0]["title"] == "User can log in"
        assert len(result["scenarios"][0]["steps"]) == 3

    def test_multiple_scenarios(self, tmp_path):
        f = tmp_path / "test_multi.feature"
        f.write_text(
            "@prerequisites\n"
            "Feature: Components are reachable\n"
            "\n"
            "  Scenario: Connect is reachable\n"
            "    Given Connect is configured\n"
            "    When I request the health endpoint\n"
            "    Then the server responds OK\n"
            "\n"
            "  Scenario: Workbench is reachable\n"
            "    Given Workbench is configured\n"
            "    When I request the health endpoint\n"
            "    Then the server responds OK\n"
        )
        result = parse_feature_file(f)
        assert len(result["scenarios"]) == 2
        assert result["scenarios"][0]["title"] == "Connect is reachable"
        assert result["scenarios"][1]["title"] == "Workbench is reachable"

    def test_and_but_steps(self, tmp_path):
        f = tmp_path / "test_steps.feature"
        f.write_text(
            "@connect\n"
            "Feature: Steps test\n"
            "\n"
            "  Scenario: Complex steps\n"
            "    Given a precondition\n"
            "    And another precondition\n"
            "    When something happens\n"
            "    Then result is expected\n"
            "    But not this other thing\n"
        )
        result = parse_feature_file(f)
        steps = result["scenarios"][0]["steps"]
        assert len(steps) == 5
        assert steps[1].startswith("And ")
        assert steps[4].startswith("But ")

    def test_relative_to(self, tmp_path):
        subdir = tmp_path / "tests" / "connect"
        subdir.mkdir(parents=True)
        f = subdir / "test_auth.feature"
        f.write_text("@connect\nFeature: Auth\n\n  Scenario: Login\n    Given ready\n")
        result = parse_feature_file(f, relative_to=tmp_path)
        assert result["file"] == "tests/connect/test_auth.feature"

    def test_no_description(self, tmp_path):
        f = tmp_path / "test_no_desc.feature"
        f.write_text(
            "@security\n"
            "Feature: HTTPS enforcement\n"
            "\n"
            "  Scenario: All endpoints use HTTPS\n"
            "    Given the server URL\n"
            "    Then the scheme is HTTPS\n"
        )
        result = parse_feature_file(f)
        assert result["title"] == "HTTPS enforcement"
        assert result["description"] == ""

    def test_scenario_outline(self, tmp_path):
        f = tmp_path / "test_outline.feature"
        f.write_text(
            "@connect\n"
            "Feature: Outline test\n"
            "\n"
            "  Scenario Outline: Deploy <type> content\n"
            "    Given Connect is accessible\n"
            "    When I deploy a <type> bundle\n"
            "    Then the content is running\n"
            "\n"
            "    Examples:\n"
            "      | type   |\n"
            "      | shiny  |\n"
            "      | rmd    |\n"
        )
        result = parse_feature_file(f)
        assert len(result["scenarios"]) == 1
        assert result["scenarios"][0]["title"] == "Deploy <type> content"
        assert len(result["scenarios"][0]["steps"]) == 3
