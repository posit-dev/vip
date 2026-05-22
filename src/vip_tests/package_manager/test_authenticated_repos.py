"""Step definitions for Package Manager authenticated repository checks.

Authenticated repos require a token to download package content
(see https://docs.posit.co/rspm/admin/repositories.html#authenticated-repos).
These scenarios are all skipped when no PM token is configured.
"""

from __future__ import annotations

import httpx
import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_authenticated_repos.feature", "At least one authenticated repository is configured")
def test_authenticated_repo_exists():
    pass


@scenario(
    "test_authenticated_repos.feature",
    "Authenticated repository denies access without a token",
)
def test_authenticated_repo_denies_without_token():
    pass


@scenario(
    "test_authenticated_repos.feature",
    "Authenticated repository allows access with a token",
)
def test_authenticated_repo_allows_with_token():
    pass


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@given("Package Manager is running")
def pm_running(pm_client):
    assert pm_client is not None, "Package Manager client not configured"
    status = pm_client.health()
    assert status < 400, f"Package Manager returned HTTP {status}"


@given("a Package Manager token is configured")
def pm_token_configured(vip_config):
    if not vip_config.package_manager.token:
        pytest.skip(
            "No Package Manager token configured "
            "(set [package_manager].token or VIP_PACKAGE_MANAGER_TOKEN)"
        )


@given("an authenticated repository is configured", target_fixture="auth_repo")
def authenticated_repo(pm_client):
    auth_repos = pm_client.list_authenticated_repos()
    if not auth_repos:
        pytest.skip("No authenticated repositories configured in Package Manager")
    testable = [r.get("name") for r in auth_repos if r.get("name") is not None]
    if not testable:
        types = sorted({r.get("type", "?") for r in auth_repos})
        pytest.skip(
            f"No authenticated repositories have a name to query via "
            f"/__api__/repos/{{name}}/packages (found types: {types})"
        )
    return testable[0]


@when("I list authenticated repositories", target_fixture="auth_repo_list")
def list_authenticated_repos(pm_client):
    return pm_client.list_authenticated_repos()


@when(
    "I query the authenticated repository without a token",
    target_fixture="unauth_response",
)
def query_without_token(pm_client, auth_repo):
    resp = httpx.get(
        f"{pm_client.base_url}/__api__/repos/{auth_repo}/packages",
        timeout=15,
        verify=pm_client.verify,
    )
    return resp


@when(
    "I query the authenticated repository with the configured token",
    target_fixture="auth_response",
)
def query_with_token(pm_client, vip_config, auth_repo):
    resp = pm_client._client.get(f"{pm_client.base_url}/__api__/repos/{auth_repo}/packages")
    return resp


@then("at least one authenticated repository exists")
def auth_repos_exist(auth_repo_list):
    if not auth_repo_list:
        pytest.skip("No authenticated repositories configured in Package Manager")
    assert len(auth_repo_list) > 0


@then("access is denied")
def access_denied(unauth_response):
    assert unauth_response.status_code in (401, 403, 404), (
        f"Expected 401/403/404 from unauthenticated request, got {unauth_response.status_code}"
    )


@then("the repository responds successfully")
def repo_responds(auth_response):
    assert auth_response.status_code < 400, (
        f"Authenticated request to repo failed with HTTP {auth_response.status_code}"
    )
