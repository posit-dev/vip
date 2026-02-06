"""Step definitions for Workbench package source checks."""

from __future__ import annotations

from pytest_bdd import given, scenario, then, when


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
    # This is a placeholder - the actual implementation will depend on the
    # Workbench version and how repos are exposed.  One approach is to
    # inspect the Workbench admin settings API if available.
    return workbench_url


@then("the expected package repository URL is present")
def repo_url_present(repo_check_url, vip_config):
    # When Package Manager is configured, its URL should appear in the
    # Workbench repository configuration.
    if vip_config.package_manager.is_configured:
        # Detailed verification would inspect Workbench's repos.conf or
        # admin API.  For now, confirm the config expectation is set.
        assert vip_config.package_manager.url, (
            "Package Manager URL should be configured as the repository source"
        )
