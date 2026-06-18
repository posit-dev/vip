"""Step definitions for Connect Chronicle usage data collection tests."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenario, then, when


@pytest.mark.min_version(product="connect", version="2026.06.0")
@scenario("test_chronicle.feature", "Chronicle reports enabled and ready")
def test_chronicle_status():
    pass


@given("Chronicle usage data collection is enabled")
def chronicle_is_enabled(chronicle_enabled):
    if not chronicle_enabled:
        pytest.skip("Chronicle is not enabled in vip.toml")


@when("I query the Chronicle status endpoint", target_fixture="chronicle_status")
def query_chronicle_status(connect_client):
    return connect_client.chronicle_status()


@then("Chronicle reports it is enabled")
def chronicle_reports_enabled(chronicle_status):
    assert chronicle_status.get("enabled") is True, (
        f"Chronicle is declared enabled but Connect reports it is not: {chronicle_status}"
    )


@then("Chronicle reports it is ready")
def chronicle_reports_ready(chronicle_status):
    assert chronicle_status.get("ready") is True, (
        f"Chronicle is enabled but its subprocess is not ready: {chronicle_status}"
    )
