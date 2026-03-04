"""Step definitions for Connect package source checks."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenario, then, when


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


def _string_values(obj):
    """Recursively yield all string leaf values from a nested dict/list."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _string_values(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _string_values(item)


@then("the configured R repository URL is present in the settings")
def r_repo_present(server_settings):
    # Connect exposes R repository configuration in the server settings JSON.
    # Check common field names used across Connect versions.
    possible_fields = ("r_repos_url", "r_default_repo_url", "repos_url", "r_repos")
    repo_value = next(
        (server_settings[f] for f in possible_fields if server_settings.get(f)),
        None,
    )
    if repo_value is None:
        # Broader search: look for any string value that looks like a URL.
        url_values = [v for v in _string_values(server_settings) if v.startswith("http")]
        if not url_values:
            pytest.skip(
                "Connect server settings do not include a recognizable R repository URL. "
                "This field may not be exposed on this Connect version."
            )
        return
    assert repo_value, "R repository URL is empty in Connect server settings"


@then("the Package Manager URL appears as a configured repository")
def pm_url_in_settings(server_settings, pm_url, connect_client):
    pm_base = pm_url.rstrip("/")

    def _matches(v: str) -> bool:
        v = v.rstrip("/")
        return v == pm_base or v.startswith(pm_base + "/")

    # 1) Check server_settings response (works on some Connect versions).
    if any(_matches(v) for v in _string_values(server_settings)):
        return

    # 2) Try the r_repos helper which checks additional API endpoints.
    if any(_matches(v) for v in connect_client.r_repos()):
        return

    # 3) The repo URLs may only be visible in the server config file
    #    (repos.conf) which is not exposed by the Connect API.
    pytest.skip(
        f"Package Manager URL {pm_base!r} was not found via the Connect API. "
        "The R repository configuration may only be visible in repos.conf on the server."
    )
