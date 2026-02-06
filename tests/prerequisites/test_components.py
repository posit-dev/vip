"""Step definitions for prerequisite component checks."""

from __future__ import annotations

import pytest
from pytest_bdd import scenario, given, when, then, parsers

import httpx


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

@scenario("test_components.feature", "Connect server is reachable")
def test_connect_reachable():
    pass


@scenario("test_components.feature", "Workbench server is reachable")
def test_workbench_reachable():
    pass


@scenario("test_components.feature", "Package Manager server is reachable")
def test_package_manager_reachable():
    pass


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

@given("Connect is configured in vip.toml")
def connect_configured(vip_config):
    if not vip_config.connect.is_configured:
        pytest.skip("Connect is not configured")


@given("Workbench is configured in vip.toml")
def workbench_configured(vip_config):
    if not vip_config.workbench.is_configured:
        pytest.skip("Workbench is not configured")


@given("Package Manager is configured in vip.toml")
def package_manager_configured(vip_config):
    if not vip_config.package_manager.is_configured:
        pytest.skip("Package Manager is not configured")


@when("I request the Connect health endpoint", target_fixture="health_response")
def request_connect_health(vip_config):
    resp = httpx.get(f"{vip_config.connect.url}/__api__/v1/server_settings", timeout=15)
    return resp


@when("I request the Workbench health endpoint", target_fixture="health_response")
def request_workbench_health(vip_config):
    resp = httpx.get(f"{vip_config.workbench.url}/health-check", timeout=15)
    return resp


@when("I request the Package Manager status endpoint", target_fixture="health_response")
def request_pm_health(vip_config):
    resp = httpx.get(f"{vip_config.package_manager.url}/__api__/status", timeout=15)
    return resp


@then("the server responds with a successful status code")
def server_responds_ok(health_response):
    assert health_response.status_code < 400, (
        f"Expected success, got HTTP {health_response.status_code}"
    )
