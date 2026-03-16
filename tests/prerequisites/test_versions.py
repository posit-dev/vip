"""Step definitions for product version verification checks."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_versions.feature", "Connect version matches configuration")
def test_connect_version():
    pass


@scenario("test_versions.feature", "Workbench version matches configuration")
def test_workbench_version():
    pass


@scenario("test_versions.feature", "Package Manager version matches configuration")
def test_package_manager_version():
    pass


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@given(
    "Connect is configured in vip.toml with a version expectation",
    target_fixture="connect_expected_version",
)
def connect_version_configured(vip_config):
    if not vip_config.connect.is_configured:
        pytest.skip("Connect is not configured")
    if not vip_config.connect.version:
        pytest.skip(
            "No Connect version configured in vip.toml — set connect.version to enable this check"
        )
    return vip_config.connect.version


@given(
    "Workbench is configured in vip.toml with a version expectation",
    target_fixture="workbench_expected_version",
)
def workbench_version_configured(vip_config):
    if not vip_config.workbench.is_configured:
        pytest.skip("Workbench is not configured")
    if not vip_config.workbench.version:
        pytest.skip(
            "No Workbench version configured in vip.toml — "
            "set workbench.version to enable this check"
        )
    return vip_config.workbench.version


@given(
    "Package Manager is configured in vip.toml with a version expectation",
    target_fixture="pm_expected_version",
)
def pm_version_configured(vip_config):
    if not vip_config.package_manager.is_configured:
        pytest.skip("Package Manager is not configured")
    if not vip_config.package_manager.version:
        pytest.skip(
            "No Package Manager version configured in vip.toml — "
            "set package_manager.version to enable this check"
        )
    return vip_config.package_manager.version


@when("I fetch the Connect server version", target_fixture="connect_running_version")
def fetch_connect_version(connect_client):
    info = connect_client.server_settings()
    version = info.get("version")
    if not version:
        pytest.skip("Connect server_settings did not return a version field")
    return version


@when("I fetch the Workbench server version", target_fixture="workbench_running_version")
def fetch_workbench_version(workbench_client):
    try:
        info = workbench_client.server_settings()
    except Exception as exc:
        pytest.skip(f"Workbench server settings endpoint not available: {exc}")
    version = info.get("version")
    if not version:
        pytest.skip("Workbench server_settings did not return a version field")
    return version


@when("I fetch the Package Manager server version", target_fixture="pm_running_version")
def fetch_pm_version(pm_client):
    info = pm_client.status()
    version = info.get("version")
    if not version:
        pytest.skip("Package Manager status endpoint did not return a version field")
    return version


@then("the Connect version matches the configured value")
def assert_connect_version(connect_running_version, connect_expected_version):
    assert connect_running_version == connect_expected_version, (
        f"Connect version mismatch: running={connect_running_version!r}, "
        f"configured={connect_expected_version!r}"
    )


@then("the Workbench version matches the configured value")
def assert_workbench_version(workbench_running_version, workbench_expected_version):
    assert workbench_running_version == workbench_expected_version, (
        f"Workbench version mismatch: running={workbench_running_version!r}, "
        f"configured={workbench_expected_version!r}"
    )


@then("the Package Manager version matches the configured value")
def assert_pm_version(pm_running_version, pm_expected_version):
    assert pm_running_version == pm_expected_version, (
        f"Package Manager version mismatch: running={pm_running_version!r}, "
        f"configured={pm_expected_version!r}"
    )
