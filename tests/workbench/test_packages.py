"""Step definitions for Workbench package source checks."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page
from pytest_bdd import given, scenario, then, when

from tests.workbench.conftest import workbench_login


@pytest.mark.skip(
    reason="NYI: admin page scraping is fragile and doesn't reflect actual session config. "
    "Rework to start an R session and check getOption('repos') instead."
)
@scenario("test_packages.feature", "R repos.conf points to the expected repository")
def test_r_repo_configured():
    pass


@given("the user is logged in to Workbench")
def user_logged_in(
    page: Page,
    workbench_url: str,
    test_username: str,
    test_password: str,
    auth_provider: str,
    interactive_auth: bool,
):
    """Log in to Workbench and verify homepage loads."""
    workbench_login(
        page, workbench_url, test_username, test_password, auth_provider, interactive_auth
    )


@when(
    "I check the configured R repositories in the session",
    target_fixture="repo_check_url",
)
def check_r_repos(page, workbench_url):
    # Navigate to the Workbench admin R configuration page to inspect
    # the configured R package repositories (repos.conf settings).
    repo_urls: list[str] = []
    for path in ("/admin/r", "/admin/", "/s/admin/r", "/s/admin/"):
        try:
            resp = page.goto(f"{workbench_url}{path}", wait_until="load", timeout=15000)
            if resp and resp.status < 400:
                content = page.content()
                # Extract https:// URLs that look like package repository sources.
                found = re.findall(r'https?://[^\s<>"\']+', content)
                repo_urls.extend(found)
                if repo_urls:
                    break
        except Exception:
            continue

    if not repo_urls:
        pytest.skip(
            "Could not retrieve R repository configuration from the Workbench admin panel. "
            "Verify that the test user has admin access, or configure the test to use an "
            "R session (getOption('repos')) to inspect the repository settings."
        )

    return repo_urls


@then("the expected package repository URL is present")
def repo_url_present(repo_check_url, vip_config):
    if not vip_config.package_manager.is_configured:
        pytest.skip("Package Manager URL is not configured in vip.toml; cannot verify R repos")
    expected = vip_config.package_manager.url.rstrip("/")
    # Match URLs that are equal to the expected base or extend it with a path.
    found = any(u.rstrip("/") == expected or u.startswith(expected + "/") for u in repo_check_url)
    assert found, (
        f"Package Manager URL {expected!r} not found in Workbench R repository configuration. "
        f"Found URLs: {repo_check_url[:10]}"
    )
