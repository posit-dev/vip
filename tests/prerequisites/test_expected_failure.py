"""Expected failure test to demonstrate failure rendering in the VIP report.

This test always fails in CI because Workbench is never configured in the
preview workflow. It exists so that the report preview includes at least
one failure, making it easy to verify how failures are displayed.
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
    "Workbench server is reachable but not configured",
)
def test_workbench_expected_failure():
    pass


@given("Workbench is expected to be configured")
def workbench_expected():
    pass


@when("I check the Workbench configuration", target_fixture="wb_configured")
def check_workbench_config(vip_config):
    return vip_config.workbench.is_configured


@then("Workbench should be reachable")
def workbench_reachable(wb_configured):
    assert wb_configured, (
        "Workbench is not configured. "
        "This is an expected failure used to demonstrate report rendering. "
        "Set [workbench] url in vip.toml to resolve."
    )
