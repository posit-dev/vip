"""Step definitions for Connect runtime version checks."""

from __future__ import annotations

import pytest
from pytest_bdd import scenario, given, when, then


@scenario("test_runtime_versions.feature", "Expected R versions are available on Connect")
def test_r_versions():
    pass


@scenario("test_runtime_versions.feature", "Expected Python versions are available on Connect")
def test_python_versions():
    pass


@given("Connect is accessible at the configured URL")
def connect_accessible(connect_client):
    assert connect_client is not None


@given("expected R versions are specified in vip.toml")
def r_versions_specified(expected_r_versions):
    if not expected_r_versions:
        pytest.skip("No expected R versions specified in vip.toml [runtimes]")


@given("expected Python versions are specified in vip.toml")
def python_versions_specified(expected_python_versions):
    if not expected_python_versions:
        pytest.skip("No expected Python versions specified in vip.toml [runtimes]")


@when("I query Connect for available R versions", target_fixture="available_r")
def query_r_versions(connect_client):
    return connect_client.r_versions()


@when("I query Connect for available Python versions", target_fixture="available_python")
def query_python_versions(connect_client):
    return connect_client.python_versions()


@then("all expected R versions are present")
def r_versions_present(expected_r_versions, available_r):
    missing = [v for v in expected_r_versions if v not in available_r]
    assert not missing, (
        f"Missing R versions on Connect: {missing}. Available: {available_r}"
    )


@then("all expected Python versions are present")
def python_versions_present(expected_python_versions, available_python):
    missing = [v for v in expected_python_versions if v not in available_python]
    assert not missing, (
        f"Missing Python versions on Connect: {missing}. Available: {available_python}"
    )
