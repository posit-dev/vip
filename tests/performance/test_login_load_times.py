"""Step definitions for login and page load time tests."""

from __future__ import annotations

import time

import pytest
from pytest_bdd import scenario, given, when, then

import httpx


@scenario("test_login_load_times.feature", "Connect login page loads within acceptable time")
def test_connect_load_time():
    pass


@scenario("test_login_load_times.feature", "Workbench login page loads within acceptable time")
def test_workbench_load_time():
    pass


@scenario("test_login_load_times.feature", "Package Manager home page loads within acceptable time")
def test_pm_load_time():
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
def pm_configured(vip_config):
    if not vip_config.package_manager.is_configured:
        pytest.skip("Package Manager is not configured")


@when("I measure the Connect login page load time", target_fixture="load_time")
def measure_connect_load(vip_config):
    start = time.monotonic()
    resp = httpx.get(f"{vip_config.connect.url}/__login__", follow_redirects=True, timeout=30)
    elapsed = time.monotonic() - start
    resp.raise_for_status()
    return elapsed


@when("I measure the Workbench login page load time", target_fixture="load_time")
def measure_workbench_load(vip_config):
    start = time.monotonic()
    resp = httpx.get(vip_config.workbench.url, follow_redirects=True, timeout=30)
    elapsed = time.monotonic() - start
    resp.raise_for_status()
    return elapsed


@when("I measure the Package Manager home page load time", target_fixture="load_time")
def measure_pm_load(vip_config):
    start = time.monotonic()
    resp = httpx.get(vip_config.package_manager.url, follow_redirects=True, timeout=30)
    elapsed = time.monotonic() - start
    resp.raise_for_status()
    return elapsed


@then("the page loads in under 10 seconds")
def load_time_ok(load_time):
    assert load_time < 10, f"Page load took {load_time:.2f}s (threshold: 10s)"
