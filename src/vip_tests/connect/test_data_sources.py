"""Step definitions for Connect external data source tests."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenario, then, when

from vip_tests.helpers import check_data_source_connectivity


@scenario("test_data_sources.feature", "External data sources are reachable from Connect")
def test_data_sources_reachable():
    pass


@given("external data sources are configured in vip.toml")
def data_sources_configured(data_sources):
    if not data_sources:
        pytest.skip("No data sources configured in vip.toml")


@when("I test connectivity to each data source", target_fixture="ds_results")
def test_connectivity(data_sources):
    return check_data_source_connectivity(data_sources)


@then("all data sources respond successfully")
def all_ok(ds_results):
    failures = [r for r in ds_results if not r["ok"]]
    assert not failures, f"Data source failures: {failures}"
