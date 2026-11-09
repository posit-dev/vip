"""Drift guard: every product-configuration Given step has a matching ``@requires_*`` tag.

The plugin deselects scenarios for unconfigured products from ``@requires_*`` tags alone,
so a ``Given Connect is configured in vip.toml`` step without ``@requires_connect`` would be
collected and skipped instead of deselected.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from gherkin.parser import Parser

_VIP_TESTS = Path(__file__).resolve().parent.parent / "src" / "vip_tests"

# Given-step prefix → the tag that must accompany it.
_GIVEN_PREFIXES = {
    "Connect is configured": "requires_connect",
    "Workbench is configured": "requires_workbench",
    "Package Manager is configured": "requires_package_manager",
}

# Example-table ``product`` value → the tag its Examples block must carry.
_PRODUCT_VALUES = {
    "Connect": "requires_connect",
    "Workbench": "requires_workbench",
    "Package Manager": "requires_package_manager",
}


def _tags(node: dict) -> set[str]:
    return {t["name"].lstrip("@") for t in node.get("tags", [])}


def _scenarios(feature: dict) -> Iterator[tuple[dict, set[str]]]:
    """Yield each scenario with the tags it inherits from its feature and rule."""
    for child in feature["children"]:
        if "scenario" in child:
            yield child["scenario"], _tags(feature)
        elif "rule" in child:
            rule = child["rule"]
            for rule_child in rule["children"]:
                if "scenario" in rule_child:
                    yield rule_child["scenario"], _tags(feature) | _tags(rule)


def _given_texts(scenario: dict) -> Iterator[str]:
    """Yield the text of Given steps, including And/But steps that continue a Given."""
    in_given = False
    for step in scenario["steps"]:
        if step["keywordType"] != "Conjunction":
            in_given = step["keywordType"] == "Context"
        if in_given:
            yield step["text"]


def _problems(path: Path) -> Iterator[str]:
    doc = Parser().parse(path.read_text(encoding="utf-8"))
    feature = doc.get("feature")
    if feature is None:
        return
    for scenario, inherited in _scenarios(feature):
        where = f"{path.relative_to(_VIP_TESTS)}: {scenario['name']!r}"
        tags = inherited | _tags(scenario)
        for text in _given_texts(scenario):
            for prefix, tag in _GIVEN_PREFIXES.items():
                if text.startswith(prefix) and tag not in tags:
                    yield f"{where}: step {text!r} needs @{tag}"
            if text.startswith("<") and "is configured" in text:
                for examples in scenario["examples"]:
                    header = [c["value"] for c in examples["tableHeader"]["cells"]]
                    col = header.index("product")
                    for row in examples["tableBody"]:
                        value = row["cells"][col]["value"]
                        row_tag = _PRODUCT_VALUES.get(value)
                        if row_tag and row_tag not in tags | _tags(examples):
                            yield f"{where}: Examples row {value!r} needs @{row_tag}"


_FEATURES = sorted(_VIP_TESTS.rglob("*.feature"))


def test_feature_files_found():
    assert len(_FEATURES) > 40, _VIP_TESTS


@pytest.mark.parametrize("path", _FEATURES, ids=lambda p: str(p.relative_to(_VIP_TESTS)))
def test_requires_tags_match_given_steps(path: Path):
    assert list(_problems(path)) == []


def test_guard_catches_missing_tags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The guard reports both a scenario-level and an Examples-level missing tag."""
    monkeypatch.setattr(f"{__name__}._VIP_TESTS", tmp_path)
    feature = tmp_path / "test_missing.feature"
    feature.write_text(
        "Feature: Missing tags\n"
        "  Scenario: Untagged guard\n"
        "    Given a precondition\n"
        "    And Connect is configured in vip.toml\n"
        "\n"
        "  Scenario Outline: <product> check\n"
        "    Given <product> is configured in vip.toml\n"
        "\n"
        "    @requires_connect\n"
        "    Examples:\n"
        "      | product   |\n"
        "      | Connect   |\n"
        "\n"
        "    Examples:\n"
        "      | product   |\n"
        "      | Workbench |\n",
        encoding="utf-8",
    )
    problems = list(_problems(feature))
    assert len(problems) == 2
    assert "needs @requires_connect" in problems[0]
    assert "'Workbench' needs @requires_workbench" in problems[1]
