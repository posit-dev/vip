"""Step definitions for Package Manager web UI smoke tests.

These drive a real browser (Playwright) against the deployed Package Manager
UI to confirm the non-admin surfaces an end user relies on — the homepage,
package search, and package detail — render after a deployment. They complement
the API-level checks in the other package_manager feature files, which never
exercise the browser.

The search and detail checks are parametrized per ecosystem (CRAN, PyPI,
Bioconductor, OpenVSX) so coverage scales with whatever the target deployment
actually serves: each ecosystem confirms package availability over the API
first, and *skips* when that repo isn't configured/synced rather than failing.
This mirrors the granularity of the API-level test_repos scenarios, so a
minimal deployment (say CRAN + PyPI only) runs those two and skips the rest.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import given, parsers, scenarios, then, when

from vip.config import VIPConfig
from vip.version import ProductVersion
from vip_tests.package_manager.pages import (
    Homepage,
    PackageDetailPage,
    PackagesPage,
    open_homepage,
    open_package_detail_via_click,
    open_repo_packages,
    search_packages,
)
from vip_tests.package_manager.pages.ui import TIMEOUT_ELEMENT, TIMEOUT_PAGE_LOAD

scenarios("test_ui.feature")

# Package Manager 2026.06.0 shipped a redesigned homepage: the hero, the
# repository-selection card, and the home package-search bar all use new
# data-automation hooks that don't exist on earlier versions (which render a
# different homepage entirely, with a repo-scoped nav search box). The version
# matrix in packagemanager-smoke.yml runs this suite across the support window,
# so the homepage scenario is skipped below on versions that predate the
# redesign — its API-driven siblings still run there. This mirrors
# @pytest.mark.min_version, which can't gate a single bulk-registered
# scenarios() scenario here.
_HOMEPAGE_REDESIGN_MIN_VERSION = "2026.06.0"


# Maps the Gherkin <ecosystem> name to how we find a repo that serves it and a
# known package to exercise. The package names match the API-level test_repos
# scenarios so the UI tests lean on content the deployment is already expected
# to serve. `available` confirms the package over the API before we drive the
# browser, so a UI failure means the UI is broken — not that the repo is
# unsynced.
_ECOSYSTEMS: dict[str, dict] = {
    "CRAN": {
        "type": "cran",
        "hint": "cran",
        "package": "Matrix",
        "available": lambda c, r, p: c.cran_package_available(r, p),
    },
    "PyPI": {
        "type": "pypi",
        "hint": "pypi",
        "package": "requests",
        "available": lambda c, r, p: c.pypi_package_available(r, p),
    },
    "Bioconductor": {
        "type": "bioconductor",
        "hint": "bioc",
        "package": "BiocGenerics",
        "available": lambda c, r, p: c.bioconductor_package_available(r, p),
    },
    "OpenVSX": {
        "type": "vsx",
        "hint": "vsx",
        "package": "golang.Go",
        "available": lambda c, r, p: c.openvsx_extension_available(r, p),
    },
}


def _find_ui_target(pm_client, ecosystem: str) -> dict[str, str]:
    """Return the first repo of *ecosystem* that serves its known package.

    Matches by repo ``type`` or a name hint (a deployment may name a repo
    ``cran`` without setting a canonical type), then confirms availability over
    the API. Returns ``{}`` when nothing suitable is configured/synced.
    """
    eco = _ECOSYSTEMS[ecosystem]
    for repo in pm_client.list_repos():
        name = repo.get("name", "")
        type_matches = (repo.get("type") or "").lower() == eco["type"]
        hint_matches = eco["hint"] in name.lower()
        if not (type_matches or hint_matches):
            continue
        if eco["available"](pm_client, name, eco["package"]):
            return {"repo": name, "package": eco["package"], "ecosystem": ecosystem}
    return {}


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@given("the Package Manager web UI is reachable")
def ui_reachable(pm_client):
    if pm_client is None:
        pytest.skip("Package Manager is not configured")
    status = pm_client.health()
    assert status < 400, f"Package Manager returned HTTP {status}"


@given(
    parsers.parse('a "{ecosystem}" repository with a known package is available'),
    target_fixture="ui_target",
)
def ui_target(pm_client, ecosystem: str) -> dict[str, str]:
    if ecosystem not in _ECOSYSTEMS:
        pytest.fail(f"Unknown ecosystem in feature examples: {ecosystem!r}")
    target = _find_ui_target(pm_client, ecosystem)
    if not target:
        pkg = _ECOSYSTEMS[ecosystem]["package"]
        pytest.skip(
            f"No {ecosystem} repository with {pkg!r} available — repo may not be synced yet"
        )
    return target


@when("I open the Package Manager homepage")
def when_open_homepage(page: Page, pm_url: str):
    open_homepage(page, pm_url)


def _skip_if_homepage_predates_redesign(vip_config: VIPConfig) -> None:
    """Skip the homepage scenario on Package Manager versions older than the
    2026.06.0 redesign.

    A version we can't parse (or that isn't set) runs optimistically rather
    than skipping, so a genuine homepage regression on a current deployment —
    where the version is often left unset — isn't hidden behind a skip. Only a
    version we can positively identify as older is gated out.
    """
    version = vip_config.package_manager.version
    if not version:
        return
    try:
        deployed = ProductVersion(version)
    except ValueError:
        return
    if deployed < ProductVersion(_HOMEPAGE_REDESIGN_MIN_VERSION):
        pytest.skip(
            f"Homepage redesign requires Package Manager >= "
            f"{_HOMEPAGE_REDESIGN_MIN_VERSION}; deployed {version}"
        )


@then("the homepage hero, repository selector, and package search bar are visible")
def then_homepage_surfaces(page: Page, vip_config: VIPConfig):
    _skip_if_homepage_predates_redesign(vip_config)
    expect(page.locator(Homepage.HERO_TITLE)).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)
    expect(page.locator(Homepage.REPO_SELECTION_CARD)).to_be_visible(timeout=TIMEOUT_ELEMENT)
    # Presence (attached) rather than visibility is the least layout-sensitive
    # signal that the search bar rendered.
    expect(page.locator(Homepage.SEARCH_BAR)).to_be_attached(timeout=TIMEOUT_ELEMENT)


@when("I search for that package in the web UI")
def when_search(page: Page, pm_url: str, ui_target: dict[str, str]):
    open_repo_packages(page, pm_url, ui_target["repo"])
    search_packages(page, ui_target["package"])


@then("the package appears in the search results")
def then_search_result(page: Page):
    # We searched for a package confirmed to exist over the API, so the search
    # returning at least one result row is the signal that search works. Assert
    # on the shared result-row selector rather than a per-id hook so this holds
    # for every ecosystem (see PackagesPage.RESULT_ITEMS).
    expect(page.locator(PackagesPage.RESULT_ITEMS).first).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)


@when("I open that package's detail page in the web UI")
def when_open_detail(page: Page, pm_url: str, ui_target: dict[str, str]):
    open_repo_packages(page, pm_url, ui_target["repo"])
    search_packages(page, ui_target["package"])
    open_package_detail_via_click(page)


@then("the package detail page shows the package metadata")
def then_detail(page: Page):
    # Assert the detail hero rendered with a non-empty title. We deliberately
    # don't assert the title equals the package id: OpenVSX detail shows the
    # extension's display name (e.g. "Go" for golang.Go), so an exact-match
    # would be ecosystem-specific. A visible, non-empty title is the shared
    # signal that the detail page rendered for every ecosystem.
    title = page.locator(PackageDetailPage.TITLE)
    expect(title).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)
    expect(title).not_to_be_empty(timeout=TIMEOUT_ELEMENT)
