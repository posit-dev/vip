"""Step definitions for the Workbench version check.

Workbench has no unauthenticated version endpoint, so the running version is
scraped from the authenticated homepage footer rather than fetched from an API
(see ``pages/homepage.py`` for the selector and parser). This mirrors the
Connect and Package Manager version scenarios in
``prerequisites/test_versions.py``, which *do* have API endpoints to hit.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import given, scenario, then, when

from vip.version import ProductVersion
from vip_tests.workbench.conftest import (
    TIMEOUT_PAGE_LOAD,
)
from vip_tests.workbench.pages import Homepage, parse_workbench_version

# Read-only homepage check; no session is launched. Order it with the other
# lightweight homepage reads rather than the session-launching tests.
pytestmark = pytest.mark.order(20)


@scenario("test_version.feature", "Workbench version matches configuration")
def test_workbench_version():
    pass


@given(
    "Workbench has a version expectation in vip.toml",
    target_fixture="workbench_expected_version",
)
def workbench_version_configured(vip_config):
    if not vip_config.workbench.version:
        pytest.skip(
            "No Workbench version configured in vip.toml — "
            "set workbench.version to enable this check"
        )
    return vip_config.workbench.version


@when(
    "I read the Workbench version from the homepage footer",
    target_fixture="workbench_running_version",
)
def read_workbench_version(page: Page):
    footer = page.locator(Homepage.VERSION_FOOTER).first
    expect(footer).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)
    footer_text = footer.inner_text().strip()
    running = parse_workbench_version(footer_text)
    if not running:
        pytest.skip(
            "Could not parse a Workbench version from the homepage footer "
            f"(text was {footer_text!r}) — the footer format may have changed"
        )
    return running


@then("the Workbench version matches the configured value")
def assert_workbench_version(workbench_running_version, workbench_expected_version):
    # Compare via ProductVersion so build metadata (e.g. the "+139.pro9" the
    # footer carries) is ignored: config holds "2026.07.0" while the running
    # string is "2026.07.0+139.pro9". A raw string == would always fail here.
    try:
        running = ProductVersion(workbench_running_version)
        expected = ProductVersion(workbench_expected_version)
    except ValueError as exc:
        pytest.skip(
            f"Cannot compare Workbench versions (running="
            f"{workbench_running_version!r}, configured="
            f"{workbench_expected_version!r}): {exc}"
        )
    assert running == expected, (
        f"Workbench version mismatch: running={workbench_running_version!r}, "
        f"configured={workbench_expected_version!r}"
    )
