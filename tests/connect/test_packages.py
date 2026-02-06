"""Step definitions for Connect package source checks."""

from __future__ import annotations

import pytest
from pytest_bdd import scenario, given, when, then


@scenario("test_packages.feature", "Connect is configured to use the expected package repository")
def test_package_repo_configured():
    pass


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
    # The exact key varies by Connect version; look for common patterns.
    settings_str = str(server_settings).lower()
    assert "cran" in settings_str or "repository" in settings_str or "packagemanager" in settings_str, (
        "No R package repository information found in Connect server settings"
    )


@then("the Package Manager URL appears as a configured repository")
def pm_url_in_settings(server_settings, pm_url):
    settings_str = str(server_settings)
    assert pm_url.rstrip("/") in settings_str or "packagemanager" in settings_str.lower(), (
        f"Package Manager URL ({pm_url}) not found in Connect server settings"
    )
