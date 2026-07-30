"""Page objects and navigation helpers for Package Manager web UI smoke tests.

Selectors mirror the ``data-automation`` hooks used by Package Manager's own
Playwright smoke suite (rstudio/package-manager:
``src/e2e/ui/selectors/selectors.go``). Package Manager is a Vue SPA that uses
hash-based routing (``createWebHashHistory``), so every in-app route lives
behind ``#/`` — a change to only the hash is a client-side navigation, not a
full page load.
"""

from __future__ import annotations

import time
import warnings

from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from vip.timeouts import timeout_scale

# Scaled the same way the Workbench UI tests scale theirs, via VIP_TIMEOUT_SCALE.
TIMEOUT_PAGE_LOAD = int(15_000 * timeout_scale())
TIMEOUT_ELEMENT = int(10_000 * timeout_scale())

# Package search gets its own, much longer ceiling. Searching a full PyPI or
# CRAN mirror is not comparable to the other waits in this module: the repo
# packages page fires an unfiltered first-page listing and a popular-packages
# query alongside the debounced search, and on a large repo those pile up.
#
# Measured, not guessed. Across 12 runs against a real deployment, the first
# result row on the ``pypi`` repo rendered in ~4s eleven times and took 53.8s
# once -- on the first search of the session, so the tail reads as a cold
# cache rather than steady-state load. (The same wait on ``cran`` was ~1s
# throughout, which is why only the large mirrors are affected.) A 15s ceiling
# sits right inside that tail, so the PyPI search and detail scenarios failed
# intermittently on a perfectly healthy deployment. 90s clears the observed
# worst case with room to spare; anything genuinely broken still fails, just
# later.
TIMEOUT_SEARCH = int(90_000 * timeout_scale())

# A search slower than this is reported but not failed: it is a real complaint
# about the deployment (nobody waits 15s for a package search) without being
# evidence that search is broken. Deliberately the same value as
# TIMEOUT_PAGE_LOAD, so every wait that previously failed now surfaces as a
# warning instead of vanishing.
SLOW_SEARCH_MS = TIMEOUT_PAGE_LOAD


def _settle_network(page: Page) -> None:
    """Best-effort wait for the SPA's network activity to go idle.

    ``networkidle`` is a heuristic — it waits for a 500ms gap in network
    activity, which a single background poll or keep-alive can defeat, so a
    timeout here is not a failure. Bound it with the module's scaled timeout so
    it honors ``VIP_TIMEOUT_SCALE`` (rather than Playwright's unscaled 30s
    default), but swallow the timeout: the explicit element and URL waits that
    follow every call are the real readiness gates, and letting a never-idle
    page fail here just makes the smoke tests flaky.
    """
    try:
        page.wait_for_load_state("networkidle", timeout=TIMEOUT_PAGE_LOAD)
    except PlaywrightTimeoutError:
        pass


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
    real SPA navigation, gives the page a best-effort chance to settle (see
    _settle_network), then gates on the search input being visible before a
    caller interacts with it — the deterministic readiness signal.
    """
    page.goto(_root(base_url) + "/#/", wait_until="load", timeout=TIMEOUT_PAGE_LOAD)
    _settle_network(page)
    page.goto(
        f"{_root(base_url)}/#/repos/{repo}/packages",
        wait_until="load",
        timeout=TIMEOUT_PAGE_LOAD,
    )
    _settle_network(page)
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


def wait_for_search_results(page: Page) -> float:
    """Wait for the first search-result row; warn when the wait was long.

    Returns the elapsed seconds. Raises ``AssertionError`` (not a raw
    Playwright timeout) when no row appears within TIMEOUT_SEARCH, so a genuine
    search outage reports as a readable failure rather than "an unexpected
    error occurred: Locator.wait_for: Timeout exceeded".

    The warning above SLOW_SEARCH_MS is the point of this helper: raising the
    ceiling alone would silently absorb a deployment whose package search takes
    a minute, which is worth telling an administrator about even though it is
    not a broken deployment.
    """
    started = time.monotonic()
    try:
        page.locator(PackagesPage.RESULT_ITEMS).first.wait_for(
            state="visible", timeout=TIMEOUT_SEARCH
        )
    except PlaywrightTimeoutError:
        raise AssertionError(
            f"No package search result rendered within {TIMEOUT_SEARCH / 1000:g}s. "
            "The package was confirmed to exist over the API before the browser "
            "was driven, so either the search UI is broken or the deployment is "
            "far slower than the timeout allows (raise it with VIP_TIMEOUT_SCALE)."
        ) from None

    elapsed = time.monotonic() - started
    if elapsed * 1000 > SLOW_SEARCH_MS:
        warnings.warn(
            f"VIP: package search took {elapsed:.1f}s to render its first result "
            f"(over the {SLOW_SEARCH_MS / 1000:g}s expected). Search works, but "
            "this is slow enough for users to notice — check Package Manager's "
            "database and the size of the repo being searched.",
            stacklevel=2,
        )
    return elapsed


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
    wait_for_search_results(page)
    page.locator(PackagesPage.RESULT_ITEMS).first.click()
    expect(page.locator(PackageDetailPage.TITLE)).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)
