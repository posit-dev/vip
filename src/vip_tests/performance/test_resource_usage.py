"""Step definitions for remote product performance under load tests."""

from __future__ import annotations

import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from pytest_bdd import given, scenario, then, when

from vip.client_auth import build_client_auth


@scenario(
    "test_resource_usage.feature", "Products respond within acceptable time under moderate load"
)
def test_response_time_under_load():
    pass


@scenario("test_resource_usage.feature", "Prometheus metrics endpoint is enabled")
def test_prometheus_metrics():
    pass


@given("at least one product is configured")
def product_configured(vip_config):
    any_configured = (
        vip_config.connect.is_configured
        or vip_config.workbench.is_configured
        or vip_config.package_manager.is_configured
    )
    if not any_configured:
        pytest.skip("No products configured")


@when("I generate moderate API traffic for 10 seconds", target_fixture="load_test_results")
def generate_traffic_and_measure_response_times(vip_config, vip_verbose):
    """Generate concurrent API traffic and collect response times."""
    # Collect (health-check URL, ingress auth) pairs from configured products.
    # The auth is per-product so each request carries the SPCS ingress token.
    targets: list[tuple[str, httpx.Auth | None]] = []
    if vip_config.connect.is_configured:
        auth = build_client_auth(vip_config, "connect", vip_config.connect.url)
        targets.append((f"{vip_config.connect.url}/__api__/server_settings", auth))
    if vip_config.workbench.is_configured:
        auth = build_client_auth(vip_config, "workbench", vip_config.workbench.url)
        targets.append((f"{vip_config.workbench.url}/health-check", auth))
    if vip_config.package_manager.is_configured:
        auth = build_client_auth(vip_config, "package_manager", vip_config.package_manager.url)
        targets.append((f"{vip_config.package_manager.url}/__api__/status", auth))

    if not targets:
        pytest.skip("No product URLs available for load testing")

    stop_at = time.monotonic() + 10
    results = []
    verbose = vip_verbose

    verify = vip_config.verify

    def _fetch_loop(url: str, auth: httpx.Auth | None):
        """Continuously fetch URL until stop_at, collecting timing and status."""
        while time.monotonic() < stop_at:
            start = time.monotonic()
            try:
                resp = httpx.get(url, timeout=10, verify=verify, auth=auth)
                elapsed = time.monotonic() - start
                results.append({"elapsed": elapsed, "status": resp.status_code, "error": None})
                if verbose:
                    print(
                        f"[load] GET {url} {resp.status_code} {elapsed:.2f}s",
                        file=sys.stderr,
                        flush=True,
                    )
            except Exception as exc:
                elapsed = time.monotonic() - start
                results.append({"elapsed": elapsed, "status": None, "error": str(exc)})
                if verbose:
                    print(
                        f"[load] GET {url} FAIL {elapsed:.2f}s {exc}",
                        file=sys.stderr,
                        flush=True,
                    )
            time.sleep(0.1)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for url, auth in targets:
            pool.submit(_fetch_loop, url, auth)

    return results


@then("the p95 response time is within the configured threshold")
def check_p95_response_time(load_test_results, performance_config):
    """Assert that the 95th percentile response time is within the configured threshold."""
    if not load_test_results:
        pytest.fail("No load test results collected")

    elapsed_times = sorted(r["elapsed"] for r in load_test_results)

    # Use statistics.quantiles for accurate p95 calculation.
    # For n < 2, fall back to max value (edge case).
    if len(elapsed_times) < 2:
        p95_time = elapsed_times[0]
    else:
        quantiles = statistics.quantiles(elapsed_times, n=100, method="inclusive")
        p95_time = quantiles[94]  # 95th percentile

    threshold = performance_config.p95_response_time
    assert p95_time < threshold, f"p95 response time was {p95_time:.2f}s (threshold: {threshold}s)"


@then("the error rate is below 10 percent")
def check_error_rate(load_test_results):
    """Assert that fewer than 10% of requests failed or timed out."""
    if not load_test_results:
        pytest.fail("No load test results collected")

    total = len(load_test_results)
    errors = sum(
        1
        for r in load_test_results
        if r["error"] is not None or (r["status"] is not None and r["status"] >= 400)
    )
    error_rate = (errors / total) * 100

    assert error_rate < 10, f"Error rate was {error_rate:.1f}% (threshold: 10%)"


@then("each product has a working Prometheus metrics endpoint")
def check_prometheus_endpoints(vip_config):
    """Verify that each configured product exposes a /metrics endpoint."""
    products_to_check = []

    if vip_config.connect.is_configured:
        products_to_check.append(("Connect", "connect", vip_config.connect.url))
    if vip_config.workbench.is_configured:
        products_to_check.append(("Workbench", "workbench", vip_config.workbench.url))
    if vip_config.package_manager.is_configured:
        products_to_check.append(
            ("Package Manager", "package_manager", vip_config.package_manager.url)
        )

    if not products_to_check:
        pytest.skip("No products configured for Prometheus check")

    failures = []
    for product_name, product_key, base_url in products_to_check:
        metrics_url = f"{base_url}/metrics"
        auth = build_client_auth(vip_config, product_key, base_url)
        try:
            resp = httpx.get(metrics_url, timeout=10, verify=vip_config.verify, auth=auth)
            if resp.status_code != 200:
                failures.append(
                    f"{product_name}: /metrics returned {resp.status_code} (expected 200)"
                )
        except Exception as exc:
            failures.append(f"{product_name}: /metrics request failed ({exc})")

    assert not failures, "Prometheus metrics endpoint check failed:\n" + "\n".join(failures)
