"""Step definitions for resource usage under workload tests."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_resource_usage.feature", "CPU and memory stay within limits during API activity")
def test_resources_under_load():
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


@when("I generate moderate API traffic for 10 seconds", target_fixture="resource_snapshot")
def generate_traffic(vip_config):
    # Pick the first configured product endpoint for traffic generation.
    urls = []
    if vip_config.connect.is_configured:
        urls.append(f"{vip_config.connect.url}/__api__/v1/server_settings")
    if vip_config.package_manager.is_configured:
        urls.append(f"{vip_config.package_manager.url}/__api__/status")

    stop_at = time.monotonic() + 10

    def _loop(url):
        while time.monotonic() < stop_at:
            try:
                httpx.get(url, timeout=10)
            except Exception:
                pass
            time.sleep(0.1)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for url in urls:
            pool.submit(_loop, url)

    # Snapshot system state after the traffic burst.
    load_avg = os.getloadavg()[0]  # 1-minute load average
    cpu_count = os.cpu_count() or 1

    mem_total = 0
    mem_available = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    mem_available = int(line.split()[1])
    except FileNotFoundError:
        pass

    return {
        "load_avg": load_avg,
        "cpu_count": cpu_count,
        "mem_total_kb": mem_total,
        "mem_available_kb": mem_available,
    }


@then("system load average is below the CPU count")
def load_ok(resource_snapshot):
    assert resource_snapshot["load_avg"] < resource_snapshot["cpu_count"] * 2, (
        f"Load average {resource_snapshot['load_avg']:.2f} exceeds "
        f"2x CPU count ({resource_snapshot['cpu_count']})"
    )


@then("available memory stays above 10 percent")
def memory_ok(resource_snapshot):
    if resource_snapshot["mem_total_kb"] == 0:
        pytest.skip("Memory info not available (non-Linux host)")
    avail_pct = (resource_snapshot["mem_available_kb"] / resource_snapshot["mem_total_kb"]) * 100
    assert avail_pct > 10, f"Only {avail_pct:.1f}% memory available (threshold: 10%)"
