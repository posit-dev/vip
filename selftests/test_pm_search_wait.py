"""Selftests for ``wait_for_search_results`` in
``src/vip_tests/package_manager/pages/ui.py``.

Package search against a full mirror is far slower than the other UI waits in
that module: measured against a real deployment, the first result row on the
``pypi`` repo rendered in ~4s eleven times out of twelve and took 53.8s once,
while ``cran`` stayed at ~1s. The shared 15s ceiling sat inside that tail, so
the PyPI search and detail scenarios failed intermittently on a healthy
deployment.

Raising the ceiling alone would trade a false failure for a silent one -- a
deployment whose package search takes a minute is worth reporting. Hence the
split: wait up to TIMEOUT_SEARCH, warn past SLOW_SEARCH_MS, fail with a
readable message only when nothing renders at all.
"""

from __future__ import annotations

import warnings

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from vip_tests.package_manager.pages.ui import (
    SLOW_SEARCH_MS,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_SEARCH,
    wait_for_search_results,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeLocator:
    """Stands in for ``page.locator(...).first``.

    *delay* is the wall-clock time ``wait_for`` pretends the row took to
    appear; *timeout_after* makes it raise Playwright's timeout instead.
    """

    def __init__(self, clock, delay=0.0, timeout_after=False):
        self._clock = clock
        self._delay = delay
        self._timeout_after = timeout_after
        self.first = self
        self.waited_with: dict | None = None

    def wait_for(self, **kwargs):
        self.waited_with = kwargs
        self._clock.advance(self._delay)
        if self._timeout_after:
            raise PlaywrightTimeoutError("Timeout exceeded")


class FakePage:
    def __init__(self, locator):
        self._locator = locator
        self.selectors: list[str] = []

    def locator(self, selector):
        self.selectors.append(selector)
        return self._locator


class FakeClock:
    """Monotonic clock the test drives, so nothing here actually sleeps."""

    def __init__(self):
        self.now = 1000.0

    def advance(self, seconds):
        self.now += seconds

    def __call__(self):
        return self.now


@pytest.fixture()
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr("vip_tests.package_manager.pages.ui.time.monotonic", fake)
    return fake


def _page(clock, **locator_kwargs):
    return FakePage(FakeLocator(clock, **locator_kwargs))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFastSearch:
    def test_returns_elapsed_without_warning(self, clock):
        page = _page(clock, delay=4.0)

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            elapsed = wait_for_search_results(page)

        assert elapsed == pytest.approx(4.0)

    def test_waits_on_the_shared_result_row_selector(self, clock):
        """Ecosystem-agnostic: the prefix hook, not a per-package id."""
        page = _page(clock, delay=1.0)

        wait_for_search_results(page)

        assert page.selectors == ["[data-automation^='package-link-']"]

    def test_uses_the_search_ceiling_not_the_page_load_one(self, clock):
        """The regression: at TIMEOUT_PAGE_LOAD this wait failed on a healthy
        deployment whose PyPI search sat in the slow tail."""
        page = _page(clock, delay=1.0)

        wait_for_search_results(page)

        assert page._locator.waited_with == {"state": "visible", "timeout": TIMEOUT_SEARCH}
        assert TIMEOUT_SEARCH > TIMEOUT_PAGE_LOAD


class TestSlowSearch:
    def test_search_past_the_threshold_warns_but_still_passes(self, clock):
        """The 53.8s observation: slow, not broken. It must be reported and
        must not fail."""
        page = _page(clock, delay=53.8)

        with pytest.warns(UserWarning, match="package search took 53.8s"):
            elapsed = wait_for_search_results(page)

        assert elapsed == pytest.approx(53.8)

    def test_warning_is_actionable(self, clock):
        page = _page(clock, delay=53.8)

        with pytest.warns(UserWarning) as record:
            wait_for_search_results(page)

        message = str(record[0].message)
        assert "Search works" in message
        assert "repo" in message

    def test_just_under_the_threshold_stays_quiet(self, clock):
        """Boundary: SLOW_SEARCH_MS is the line, and a search below it is
        unremarkable -- no warning noise on every normal run."""
        page = _page(clock, delay=(SLOW_SEARCH_MS / 1000) - 0.1)

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            wait_for_search_results(page)


class TestNoResults:
    def test_timeout_raises_a_readable_assertion_not_a_playwright_error(self, clock):
        """A raw Playwright timeout surfaces as "an unexpected error occurred:
        Locator.wait_for: Timeout 15000ms exceeded", which tells an
        administrator nothing. Fail with the diagnosis instead."""
        page = _page(clock, delay=90.0, timeout_after=True)

        with pytest.raises(AssertionError) as exc_info:
            wait_for_search_results(page)

        message = str(exc_info.value)
        assert "90s" in message
        assert "confirmed to exist over the API" in message
        assert "VIP_TIMEOUT_SCALE" in message

    def test_timeout_does_not_also_warn_about_slowness(self, clock):
        """A failure is not also a slow-search report -- one finding, not two."""
        page = _page(clock, delay=90.0, timeout_after=True)

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with pytest.raises(AssertionError):
                wait_for_search_results(page)
