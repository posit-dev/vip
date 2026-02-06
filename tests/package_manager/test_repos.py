"""Step definitions for Package Manager repository checks."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_repos.feature", "CRAN mirror is accessible")
def test_cran_mirror():
    pass


@scenario("test_repos.feature", "PyPI mirror is accessible")
def test_pypi_mirror():
    pass


@scenario("test_repos.feature", "At least one repository is configured")
def test_repo_exists():
    pass


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@given("Package Manager is running")
def pm_running(pm_client):
    assert pm_client is not None, "Package Manager client not configured"
    status = pm_client.status()
    assert status < 400, f"Package Manager returned HTTP {status}"


@when(
    'I query the CRAN repository for the "Matrix" package',
    target_fixture="package_found",
)
def query_cran(pm_client):
    repos = pm_client.list_repos()
    cran_repos = [
        r for r in repos if r.get("type") == "cran" or "cran" in r.get("name", "").lower()
    ]
    if not cran_repos:
        pytest.skip("No CRAN repository configured in Package Manager")
    repo_name = cran_repos[0]["name"]
    return pm_client.cran_package_available(repo_name, "Matrix")


@when(
    'I query the PyPI repository for the "requests" package',
    target_fixture="package_found",
)
def query_pypi(pm_client):
    repos = pm_client.list_repos()
    pypi_repos = [
        r for r in repos if r.get("type") == "pypi" or "pypi" in r.get("name", "").lower()
    ]
    if not pypi_repos:
        pytest.skip("No PyPI repository configured in Package Manager")
    repo_name = pypi_repos[0]["name"]
    return pm_client.pypi_package_available(repo_name, "requests")


@when("I list all repositories", target_fixture="repo_list")
def list_repos(pm_client):
    return pm_client.list_repos()


@then("the package is found in the repository")
def package_is_found(package_found):
    assert package_found, "Package was not found in the repository"


@then("at least one repository exists")
def repo_exists(repo_list):
    assert len(repo_list) > 0, "No repositories configured in Package Manager"
