"""Drift guard: every product-configuration Given step has a matching product tag.

The plugin deselects scenarios for unconfigured products from tags alone (``@requires_*`` or a
product marker such as ``@connect``), so a ``Given Connect is configured in vip.toml`` step
without one would be collected and skipped instead of deselected. Background steps count:
pytest-bdd runs them as part of every scenario.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from gherkin.parser import Parser

_VIP_TESTS = Path(__file__).resolve().parent.parent / "src" / "vip_tests"

# Given-step prefix → the product whose tag must accompany it.
_GIVEN_PREFIXES = {
    "Connect is configured": "connect",
    "Workbench is configured": "workbench",
    "Package Manager is configured": "package_manager",
}

# Example-table ``product`` value → the product whose tag its Examples block must carry.
_PRODUCT_VALUES = {
    "Connect": "connect",
    "Workbench": "workbench",
    "Package Manager": "package_manager",
}


def _has_tag(product: str, tags: set[str]) -> bool:
    """Either ``@requires_<product>`` or the ``@<product>`` marker deselects."""
    return f"requires_{product}" in tags or product in tags


def _tags(node: dict) -> set[str]:
    return {t["name"].lstrip("@") for t in node.get("tags", [])}


def _background_steps(children: list[dict]) -> list[dict]:
    return [step for c in children if "background" in c for step in c["background"]["steps"]]


def _scenarios(feature: dict) -> Iterator[tuple[dict, set[str], list[dict]]]:
    """Yield each scenario with the tags it inherits and the Background steps that run before it."""
    feature_bg = _background_steps(feature["children"])
    for child in feature["children"]:
        if "scenario" in child:
            yield child["scenario"], _tags(feature), feature_bg
        elif "rule" in child:
            rule = child["rule"]
            rule_bg = feature_bg + _background_steps(rule["children"])
            for rule_child in rule["children"]:
                if "scenario" in rule_child:
                    yield rule_child["scenario"], _tags(feature) | _tags(rule), rule_bg


def _given_texts(steps: list[dict]) -> Iterator[str]:
    """Yield the text of Given steps, including And/But steps that continue a Given."""
    in_given = False
    for step in steps:
        if step["keywordType"] != "Conjunction":
            in_given = step["keywordType"] == "Context"
        if in_given:
            yield step["text"]


def _problems(path: Path) -> Iterator[str]:
    doc = Parser().parse(path.read_text(encoding="utf-8"))
    feature = doc.get("feature")
    if feature is None:
        return
    for scenario, inherited, background in _scenarios(feature):
        where = f"{path.relative_to(_VIP_TESTS)}: {scenario['name']!r}"
        tags = inherited | _tags(scenario)
        for text in _given_texts(background + scenario["steps"]):
            for prefix, product in _GIVEN_PREFIXES.items():
                if text.startswith(prefix) and not _has_tag(product, tags):
                    yield f"{where}: step {text!r} needs @requires_{product}"
            if text.startswith("<") and "is configured" in text:
                yield from _examples_problems(where, scenario, tags)


def _examples_problems(where: str, scenario: dict, tags: set[str]) -> Iterator[str]:
    """Check each Examples row of a ``<product> is configured`` outline carries its product tag."""
    for examples in scenario["examples"]:
        header_row = examples.get("tableHeader")
        header = [c["value"] for c in header_row["cells"]] if header_row else []
        if "product" not in header:
            yield f"{where}: Examples table needs a 'product' column for '<...> is configured'"
            continue
        col = header.index("product")
        for row in examples["tableBody"]:
            value = row["cells"][col]["value"]
            product = _PRODUCT_VALUES.get(value)
            if product and not _has_tag(product, tags | _tags(examples)):
                yield f"{where}: Examples row {value!r} needs @requires_{product}"


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


def test_guard_reads_background_steps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A Background guard applies to every scenario under it, including inside a Rule."""
    monkeypatch.setattr(f"{__name__}._VIP_TESTS", tmp_path)
    feature = tmp_path / "test_background.feature"
    feature.write_text(
        "Feature: Background guard\n"
        "  Background:\n"
        "    Given Connect is configured in vip.toml\n"
        "\n"
        "  Scenario: Untagged\n"
        "    Then it passes\n"
        "\n"
        "  Rule: Workbench rule\n"
        "    Background:\n"
        "      Given Workbench is configured in vip.toml\n"
        "\n"
        "    @requires_connect\n"
        "    Scenario: Only Connect tagged\n"
        "      Then it passes\n",
        encoding="utf-8",
    )
    problems = list(_problems(feature))
    assert len(problems) == 2
    assert (
        "'Untagged': step 'Connect is configured in vip.toml' needs @requires_connect"
        in (problems[0])
    )
    assert "needs @requires_workbench" in problems[1]


def test_guard_accepts_product_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """``@connect`` deselects as well as ``@requires_connect``, so it satisfies the guard."""
    monkeypatch.setattr(f"{__name__}._VIP_TESTS", tmp_path)
    feature = tmp_path / "test_marker.feature"
    feature.write_text(
        "@connect\n"
        "Feature: Marker\n"
        "  Scenario: Tagged by marker\n"
        "    Given Connect is configured in vip.toml\n",
        encoding="utf-8",
    )
    assert list(_problems(feature)) == []


def test_guard_reports_examples_without_product_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """An outline whose Examples table has no ``product`` column gets a message, not a crash."""
    monkeypatch.setattr(f"{__name__}._VIP_TESTS", tmp_path)
    feature = tmp_path / "test_column.feature"
    feature.write_text(
        "Feature: Column\n"
        "  Scenario Outline: <app> check\n"
        "    Given <app> is configured in vip.toml\n"
        "\n"
        "    Examples:\n"
        "      | app     |\n"
        "      | Connect |\n",
        encoding="utf-8",
    )
    problems = list(_problems(feature))
    assert len(problems) == 1
    assert "Examples table needs a 'product' column" in problems[0]
