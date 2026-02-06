"""Step definitions for private repository checks."""

from __future__ import annotations

import pytest
from pytest_bdd import scenario, given, when, then

import httpx


@scenario("test_private_repos.feature", "Private repositories are reachable")
def test_private_repos():
    pass


@given("Package Manager is running")
def pm_running(pm_client):
    assert pm_client is not None


@given("private repositories are configured", target_fixture="private_repos")
def private_repos_configured(pm_client):
    repos = pm_client.list_repos()
    # Heuristic: repos that are not the built-in CRAN/PyPI mirrors.
    private = [r for r in repos if r.get("private", False) or "internal" in r.get("name", "").lower()]
    if not private:
        pytest.skip("No private repositories configured")
    return private


@when("I query each private repository", target_fixture="repo_responses")
def query_private_repos(pm_client, private_repos):
    results = []
    for repo in private_repos:
        name = repo["name"]
        resp = httpx.get(f"{pm_client.base_url}/{name}/latest/", timeout=15)
        results.append({"name": name, "status": resp.status_code})
    return results


@then("each repository responds successfully")
def repos_respond(repo_responses):
    failures = [r for r in repo_responses if r["status"] >= 400]
    assert not failures, f"Private repos failed: {failures}"
