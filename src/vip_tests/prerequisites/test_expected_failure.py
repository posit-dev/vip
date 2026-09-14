"""Intentional failure to demonstrate failure rendering in the VIP report.

This scenario fails by construction -- it does not depend on the state of
any configured product -- so the example report always has at least one
failure card to show what failure rendering looks like. It is disabled by
default; the example-report workflow opts in via
``VIP_ENABLE_EXPECTED_FAILURE_DEMO=1``.

An earlier version of this test asserted that Workbench *was* configured,
which only failed because CI never configured Workbench. Once CI started
configuring Workbench, the test passed and the report lost its one example
failure -- see https://github.com/posit-dev/vip/issues/73.
"""

from __future__ import annotations

import os

import pytest
from pytest_bdd import given, scenario, then, when

if not os.getenv("VIP_ENABLE_EXPECTED_FAILURE_DEMO"):
    pytest.skip(
        "Skipping demo expected-failure test; set VIP_ENABLE_EXPECTED_FAILURE_DEMO=1 to enable.",
        allow_module_level=True,
    )


@scenario(
    "test_expected_failure.feature",
    "This check intentionally fails to demonstrate failure rendering",
)
def test_intentional_failure():
    pass


@given("a check that is written to fail on purpose")
def intentional_check():
    pass


@when("the check runs as part of this example report", target_fixture="demo_outcome")
def run_intentional_check():
    return {"expected": "pass", "actual": "fail (by design)"}


@then("it fails by design, not because anything is actually broken")
def check_fails_by_design(demo_outcome):
    assert demo_outcome["actual"] == demo_outcome["expected"], (
        "This failure is intentional: it exists only to show how a failed check "
        "renders in this example report. No product configuration will resolve it."
    )
