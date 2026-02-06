"""Step definitions for Workbench runtime version checks."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_runtime_versions.feature", "Expected R versions are available on Workbench")
def test_r_versions():
    pass


@scenario("test_runtime_versions.feature", "Expected Python versions are available on Workbench")
def test_python_versions():
    pass


@given("the user is logged in to Workbench")
def user_logged_in(page, workbench_url, test_username, test_password):
    page.goto(workbench_url)
    if "sign-in" in page.url.lower() or "login" in page.url.lower():
        page.fill("#username, [name='username']", test_username)
        page.fill("#password, [name='password']", test_password)
        page.click("button[type='submit'], #sign-in")
        page.wait_for_load_state("networkidle")


@given("expected R versions are specified in vip.toml")
def r_versions_specified(expected_r_versions):
    if not expected_r_versions:
        pytest.skip("No expected R versions specified in vip.toml [runtimes]")


@given("expected Python versions are specified in vip.toml")
def python_versions_specified(expected_python_versions):
    if not expected_python_versions:
        pytest.skip("No expected Python versions specified in vip.toml [runtimes]")


@when("I check available R versions on Workbench", target_fixture="available_r")
def check_r_versions(page, workbench_url):
    # Navigate to session creation to see the R version selector.
    page.click("text=New Session", timeout=15000)
    # Collect version options from the R version dropdown if visible.
    options = page.query_selector_all("select[name*='r'] option, [data-r-version]")
    versions = [opt.inner_text().strip() for opt in options if opt.inner_text().strip()]
    return versions


@when("I check available Python versions on Workbench", target_fixture="available_python")
def check_python_versions(page, workbench_url):
    page.click("text=New Session", timeout=15000)
    options = page.query_selector_all("select[name*='python'] option, [data-python-version]")
    versions = [opt.inner_text().strip() for opt in options if opt.inner_text().strip()]
    return versions


@then("all expected R versions are found")
def r_versions_found(expected_r_versions, available_r):
    if not available_r:
        pytest.skip("Could not detect available R versions from the Workbench UI")
    missing = [v for v in expected_r_versions if v not in available_r]
    assert not missing, f"Missing R versions on Workbench: {missing}. Available: {available_r}"


@then("all expected Python versions are found")
def python_versions_found(expected_python_versions, available_python):
    if not available_python:
        pytest.skip("Could not detect available Python versions from the Workbench UI")
    missing = [v for v in expected_python_versions if v not in available_python]
    assert not missing, (
        f"Missing Python versions on Workbench: {missing}. Available: {available_python}"
    )
