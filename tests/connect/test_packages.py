"""Step definitions for Connect package source checks."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenario, then, when


@pytest.mark.skip(
    reason="Not yet implemented: needs structured server settings parsing by Connect version"
)
@scenario("test_packages.feature", "Connect is configured to use the expected package repository")
def test_package_repo_configured():
    pass


@pytest.mark.skip(
    reason="Not yet implemented: needs structured server settings parsing by Connect version"
)
@scenario("test_packages.feature", "Package Manager URL is the default repository source")
def test_pm_is_default_repo():
    pass


@given("Connect is accessible at the configured URL")
def connect_accessible(connect_client):
    assert connect_client is not None


@given("Package Manager is configured in vip.toml")
def pm_configured(vip_config):
    if not vip_config.package_manager.is_configured:
        pytest.skip("Package Manager is not configured")


@when(
    "I query the Connect server settings for package repositories",
    target_fixture="server_settings",
)
def query_server_settings(connect_client):
    return connect_client.server_settings()


@then("the configured R repository URL is present in the settings")
def r_repo_present(server_settings):
    # TODO: Parse server settings structure by Connect version to extract
    # the actual R repository URL rather than weak string matching.
    pytest.skip("Not yet implemented")


@then("the Package Manager URL appears as a configured repository")
def pm_url_in_settings(server_settings, pm_url):
    # TODO: Parse server settings structure to verify the Package Manager
    # URL is present as a configured repository source.
    pytest.skip("Not yet implemented")
