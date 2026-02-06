"""Step definitions for Workbench package source checks."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenario, then, when


@pytest.mark.skip(reason="Not yet implemented: needs Workbench admin API or repos.conf inspection")
@scenario("test_packages.feature", "R repos.conf points to the expected repository")
def test_r_repo_configured():
    pass


@given("the user is logged in to Workbench")
def user_logged_in(page, workbench_url, test_username, test_password):
    page.goto(workbench_url)
    if "sign-in" in page.url.lower() or "login" in page.url.lower():
        page.fill("#username, [name='username']", test_username)
        page.fill("#password, [name='password']", test_password)
        page.click("button[type='submit'], #sign-in")
        page.wait_for_load_state("networkidle")


@when(
    "I check the configured R repositories in the session",
    target_fixture="repo_check_url",
)
def check_r_repos(page, workbench_url):
    # TODO: Implement actual repos.conf / admin API inspection.
    # Options:
    #   A) Query Workbench admin settings API (if available).
    #   B) Start a session, run getOption("repos") in the R console.
    #   C) Use Playwright to inspect the admin panel repo config page.
    pytest.skip("Not yet implemented")


@then("the expected package repository URL is present")
def repo_url_present(repo_check_url, vip_config):
    # TODO: Verify the Package Manager URL actually appears in Workbench's
    # repository configuration, not just that the config expectation is set.
    pytest.skip("Not yet implemented")
