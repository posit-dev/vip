from vip.gherkin import CONTROL_TAG_PREFIX, parse_feature_file

FEATURE = """@control-cfr-11-10-e @connect
Feature: Audit trail
  Scenario: Publish is recorded
    Given Connect is reachable
"""

PRODUCT_FIRST = """@connect @control-cfr-11-10-e
Feature: Audit trail
  Scenario: Publish is recorded
    Given Connect is reachable
"""


def test_control_tag_does_not_become_the_marker(tmp_path):
    """Tag order inside a feature file must not change the derived marker."""
    f = tmp_path / "t.feature"
    f.write_text(FEATURE)
    assert parse_feature_file(f)["marker"] == "connect"


def test_product_first_ordering_is_unchanged(tmp_path):
    f = tmp_path / "t.feature"
    f.write_text(PRODUCT_FIRST)
    assert parse_feature_file(f)["marker"] == "connect"


def test_all_tags_are_collected(tmp_path):
    f = tmp_path / "t.feature"
    f.write_text(FEATURE)
    assert set(parse_feature_file(f)["tags"]) == {"control-cfr-11-10-e", "connect"}


def test_scenario_level_tags_are_collected(tmp_path):
    f = tmp_path / "t.feature"
    f.write_text("@connect\nFeature: F\n  @control-access-control\n  Scenario: S\n    Given x\n")
    parsed = parse_feature_file(f)
    assert parsed["marker"] == "connect"
    assert "control-access-control" in parsed["tags"]


def test_prefix_constant():
    assert CONTROL_TAG_PREFIX == "control-"
