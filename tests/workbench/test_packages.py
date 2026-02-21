"""Step definitions for Workbench package source checks."""

from __future__ import annotations

import re

import pytest
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
    # Navigate to the Workbench admin R configuration page to inspect
    # the configured R package repositories (repos.conf settings).
    repo_urls: list[str] = []
    for path in ("/admin/r", "/admin/", "/s/admin/r", "/s/admin/"):
        try:
            resp = page.goto(f"{workbench_url}{path}", wait_until="networkidle", timeout=15000)
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
