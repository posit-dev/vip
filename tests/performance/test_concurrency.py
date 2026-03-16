"""Step definitions for concurrency / stability tests."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
from pytest_bdd import scenario, then, when


@scenario("test_concurrency.feature", "Multiple concurrent API requests to Connect succeed")
def test_connect_concurrency():
    pass


@scenario("test_concurrency.feature", "Multiple concurrent requests to Package Manager succeed")
def test_pm_concurrency():
    pass


@scenario("test_concurrency.feature", "Workbench handles concurrent health check requests")
def test_workbench_concurrency():
    pass


def _concurrent_requests(url: str, n: int) -> list[dict]:
    """Fire *n* GET requests concurrently and collect results."""
    results = []

    def _fetch():
        start = time.monotonic()
        try:
            resp = httpx.get(url, timeout=30)
            return {"status": resp.status_code, "elapsed": time.monotonic() - start, "error": None}
        except Exception as exc:
            return {"status": None, "elapsed": time.monotonic() - start, "error": str(exc)}

    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(_fetch) for _ in range(n)]
        for f in as_completed(futures):
            results.append(f.result())
    return results


@when(
    "I send 10 concurrent health-check requests to Connect",
    target_fixture="concurrent_results",
)
def concurrent_connect(vip_config, performance_config):
    url = f"{vip_config.connect.url}/__api__/server_settings"
    return _concurrent_requests(url, performance_config.concurrent_requests)


@when(
    "I send 10 concurrent status requests to Package Manager",
    target_fixture="concurrent_results",
)
def concurrent_pm(vip_config, performance_config):
    url = f"{vip_config.package_manager.url}/__api__/status"
    return _concurrent_requests(url, performance_config.concurrent_requests)


@when(
    "I send 10 concurrent health-check requests to Workbench",
    target_fixture="concurrent_results",
)
def concurrent_workbench(vip_config, performance_config):
    url = f"{vip_config.workbench.url}/health-check"
    return _concurrent_requests(url, performance_config.concurrent_requests)


@then("all requests succeed")
def all_succeed(concurrent_results):
    failures = [r for r in concurrent_results if r["error"] or (r["status"] and r["status"] >= 400)]
    assert not failures, f"Failed requests: {failures}"


@then("the average response time is under 5 seconds")
def avg_time_ok(concurrent_results, performance_config):
    avg = sum(r["elapsed"] for r in concurrent_results) / len(concurrent_results)
    threshold = performance_config.p95_response_time
    assert avg < threshold, f"Average response time was {avg:.2f}s (threshold: {threshold}s)"
