import json

FEATURE = """@connect @control-cfr-11-10-e
Feature: Audit trail
  Scenario: Publish is recorded
    Given a thing
"""

STEPS = """
from pytest_bdd import given, scenario


@scenario("t.feature", "Publish is recorded")
def test_tagged():
    pass


@given("a thing")
def a_thing():
    pass
"""


def _write_suite(pytester):
    (pytester.path / "t.feature").write_text(FEATURE)
    pytester.makepyfile(test_t=STEPS)
    (pytester.path / "vip.toml").write_text('[connect]\nurl = "https://c.example.com"\n')


def test_collects_under_strict_markers(pytester):
    _write_suite(pytester)
    result = pytester.runpytest_subprocess(
        "--vip-config", "vip.toml", "--strict-markers", "-p", "no:cacheprovider"
    )
    result.assert_outcomes(passed=1)


def test_collects_under_warnings_as_errors(pytester):
    _write_suite(pytester)
    result = pytester.runpytest_subprocess(
        "--vip-config",
        "vip.toml",
        "-W",
        "error::pytest.PytestUnknownMarkWarning",
        "-p",
        "no:cacheprovider",
    )
    result.assert_outcomes(passed=1)


def test_collects_under_both_together(pytester):
    _write_suite(pytester)
    result = pytester.runpytest_subprocess(
        "--vip-config",
        "vip.toml",
        "--strict-markers",
        "-W",
        "error::pytest.PytestUnknownMarkWarning",
        "-p",
        "no:cacheprovider",
    )
    result.assert_outcomes(passed=1)


def test_control_tags_still_reach_results_json(pytester):
    """Registration must not cost us the evidence it exists to preserve."""
    _write_suite(pytester)
    report = pytester.path / "results.json"
    pytester.runpytest_subprocess(
        "--vip-config", "vip.toml", "--vip-report", str(report), "-p", "no:cacheprovider"
    )
    markers = json.loads(report.read_text())["results"][0]["markers"]
    assert "control-cfr-11-10-e" in markers
    assert "connect" in markers
