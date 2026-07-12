"""Page objects and navigation helpers for Package Manager web UI smoke tests.

Selectors mirror the ``data-automation`` hooks used by Package Manager's own
Playwright smoke suite (rstudio/package-manager:
``src/e2e/ui/selectors/selectors.go``). Package Manager is a Vue SPA that uses
hash-based routing (``createWebHashHistory``), so every in-app route lives
behind ``#/`` — a change to only the hash is a client-side navigation, not a
full page load.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from vip.timeouts import timeout_scale

# Scaled the same way the Workbench UI tests scale theirs, via VIP_TIMEOUT_SCALE.
TIMEOUT_PAGE_LOAD = int(15_000 * timeout_scale())
TIMEOUT_ELEMENT = int(10_000 * timeout_scale())


class Homepage:
    """Selectors for the redesigned Package Manager homepage (HomePageLayout)."""

    # The hgroup that is Package Manager's canonical "I'm on the homepage" hook.
    HERO_TITLE = "[data-automation='home-title']"
    # The clickable repository-selection card that opens the repository modal.
    REPO_SELECTION_CARD = "[data-automation='repository-selection-card']"
    # The homepage's own package search bar (hidden from the navbar here).
    SEARCH_BAR = "[data-automation='search-input-home-package-search']"


class PackagesPage:
    """Selectors for a repo-scoped packages/search page."""

    # The navbar package search input, present on repo-scoped pages.
    SEARCH_INPUT = "[data-automation=search-input-package-search]"

    # Every result row (PackageListItem) renders a ``package-link-<id>`` hook.
    # Match the shared prefix rather than a specific id: it's ecosystem-agnostic
    # (OpenVSX rows key off the extension's display name, not its dotted id), so
    # this is the robust "a result rendered" signal — the same approach Package
    # Manager's own OpenVSX smoke test uses.
    RESULT_ITEMS = "[data-automation^='package-link-']"


class PackageDetailPage:
    """Selectors for a package detail (overview) page."""

    TITLE = "[data-automation=package-title]"


def _root(base_url: str) -> str:
    return base_url.rstrip("/")


def open_homepage(page: Page, base_url: str) -> None:
    """Load the homepage and wait for the SPA to hydrate its hero."""
    page.goto(_root(base_url) + "/", wait_until="load", timeout=TIMEOUT_PAGE_LOAD)
    expect(page.locator(Homepage.HERO_TITLE)).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)


def open_repo_packages(page: Page, base_url: str, repo: str) -> None:
    """Navigate to a repository's packages page and wait for it to settle.

    Resets to the app root first so the subsequent hash-only change triggers a
    real SPA navigation, then waits for network idle so the page's queries
    resolve before a caller interacts with the search input (mirrors Package
    Manager's own NavigateToPackage helper).
    """
    page.goto(_root(base_url) + "/#/", wait_until="load", timeout=TIMEOUT_PAGE_LOAD)
    page.wait_for_load_state("networkidle")
    page.goto(
        f"{_root(base_url)}/#/repos/{repo}/packages",
        wait_until="load",
        timeout=TIMEOUT_PAGE_LOAD,
    )
    page.wait_for_load_state("networkidle")
    expect(page.locator(PackagesPage.SEARCH_INPUT)).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)


def search_packages(page: Page, package: str) -> None:
    """Type a query into the packages-page search input and wait for it to commit.

    The search bar debounces input (~500ms) before committing the query to the
    URL via router.replace. Wait for that commit before returning: otherwise a
    caller that immediately clicks a result races the trailing debounce, whose
    router.replace re-renders the list and cancels the click's navigation —
    leaving you stranded on the results page. This mirrors the wait in Package
    Manager's own Search helper, which exists for exactly this reason.
    """
    page.locator(PackagesPage.SEARCH_INPUT).fill(package)
    page.wait_for_function(
        "term => decodeURIComponent(window.location.hash).includes('search=' + term)",
        arg=package,
        timeout=TIMEOUT_ELEMENT,
    )


def open_package_detail_via_click(page: Page) -> None:
    """Click the first search-result row and wait for its detail page.

    Reaching detail by clicking the result (rather than constructing a detail
    URL) keeps this ecosystem-agnostic: OpenVSX extension ids are dotted (e.g.
    ``golang.Go``), and the click path is the real flow a user reaches the
    detail page by. PackageDetails gates its hero on the package query
    resolving, so the title only renders once the data has loaded.

    Assumes a search has already been run so at least one result row is present;
    clicks the first result and waits for the detail hero.
    """
    result = page.locator(PackagesPage.RESULT_ITEMS).first
    result.wait_for(state="visible", timeout=TIMEOUT_PAGE_LOAD)
    result.click()
    expect(page.locator(PackageDetailPage.TITLE)).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)
