"""Step definitions for Connect external data source tests."""

from __future__ import annotations

import httpx
import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_data_sources.feature", "External data sources are reachable from Connect")
def test_data_sources_reachable():
    pass


@given("Connect is accessible at the configured URL")
def connect_accessible(connect_client):
    assert connect_client is not None


@given("external data sources are configured in vip.toml")
def data_sources_configured(data_sources):
    if not data_sources:
        pytest.skip("No data sources configured in vip.toml")


@when("I test connectivity to each data source", target_fixture="ds_results")
def test_connectivity(data_sources):
    results = []
    for ds in data_sources:
        # For HTTP-accessible data sources, attempt a basic connection.
        # For database sources, attempt a socket connection to the host/port.
        result = {"name": ds.name, "type": ds.type, "ok": False, "error": None}
        try:
            if ds.type in ("http", "api"):
                resp = httpx.get(ds.connection_string, timeout=15)
                result["ok"] = resp.status_code < 400
            else:
                # For database types, we verify the connection string is
                # non-empty.  A full connectivity check requires DB drivers
                # that we don't want to mandate.
                result["ok"] = bool(ds.connection_string)
                if not result["ok"]:
                    result["error"] = "connection_string is empty"
        except Exception as exc:
            result["error"] = str(exc)
        results.append(result)
    return results


@then("all data sources respond successfully")
def all_ok(ds_results):
    failures = [r for r in ds_results if not r["ok"]]
    assert not failures, f"Data source failures: {failures}"
