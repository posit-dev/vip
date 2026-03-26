"""Step definitions for concurrent user load tests.

These tests simulate multiple authenticated users making real API requests
simultaneously, verifying that each product handles concurrent user load
acceptably.  Unlike the health-check concurrency tests, every request here
carries authentication credentials and exercises a real user-facing endpoint.
"""

from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
from pytest_bdd import scenario, then, when


@scenario("test_load.feature", "Connect handles concurrent authenticated user requests")
def test_connect_load():
    pass


@scenario("test_load.feature", "Workbench handles concurrent user requests")
def test_workbench_load():
    pass


@scenario("test_load.feature", "Package Manager handles concurrent user requests")
def test_pm_load():
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_load_test(url: str, headers: dict, n: int) -> list[dict]:
    """Fire *n* authenticated GET requests concurrently and return results."""

    def _fetch():
        start = time.monotonic()
        try:
            resp = httpx.get(url, headers=headers, timeout=30)
            return {
                "elapsed": time.monotonic() - start,
                "status": resp.status_code,
                "error": None,
            }
        except Exception as exc:
            return {
                "elapsed": time.monotonic() - start,
                "status": None,
                "error": str(exc),
            }

    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(_fetch) for _ in range(n)]
        # as_completed yields results in completion order; that's fine since we
        # only use aggregate statistics (success rate, p95) on the full list.
        return [f.result() for f in as_completed(futures)]


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when(
    "I run a load test with concurrent users against Connect",
    target_fixture="load_test_results",
)
def load_test_connect(vip_config, performance_config):
    url = f"{vip_config.connect.url}/__api__/v1/content"
    headers = {"Authorization": f"Key {vip_config.connect.api_key}"}
    return _run_load_test(url, headers, performance_config.load_users)


@when(
    "I run a load test with concurrent users against Workbench",
    target_fixture="load_test_results",
)
def load_test_workbench(vip_config, performance_config):
    url = f"{vip_config.workbench.url}/api/server/settings"
    headers = {"Authorization": f"Key {vip_config.workbench.api_key}"}
    return _run_load_test(url, headers, performance_config.load_users)


@when(
    "I run a load test with concurrent users against Package Manager",
    target_fixture="load_test_results",
)
def load_test_pm(vip_config, performance_config):
    url = f"{vip_config.package_manager.url}/__api__/repos"
    headers = {"Authorization": f"Bearer {vip_config.package_manager.token}"}
    return _run_load_test(url, headers, performance_config.load_users)


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then("the load test success rate is at least 95 percent")
def load_success_rate(load_test_results):
    total = len(load_test_results)
    successes = sum(
        1
        for r in load_test_results
        if r["error"] is None and r["status"] is not None and r["status"] < 400
    )
    rate = successes / total if total else 0.0
    assert rate >= 0.95, (
        f"Load test success rate was {rate:.0%} ({successes}/{total} requests succeeded)"
    )


@then("the load test p95 response time is within the configured threshold")
def load_p95_response_time(load_test_results, performance_config):
    elapsed_times = [r["elapsed"] for r in load_test_results]
    if len(elapsed_times) < 2:
        # Not enough data points to compute quantiles; use the single value directly.
        p95 = elapsed_times[0] if elapsed_times else 0.0
    else:
        p95 = statistics.quantiles(elapsed_times, n=20)[18]  # 95th percentile
    threshold = performance_config.p95_response_time
    assert p95 <= threshold, f"Load test p95 response time was {p95:.2f}s (threshold: {threshold}s)"
