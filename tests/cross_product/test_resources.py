"""Step definitions for system resource usage checks.

These tests check the host where VIP is running.  When VIP is executed on the
same server as the Posit products (as recommended), this gives a direct view
of resource utilisation.
"""

from __future__ import annotations

import shutil

import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_resources.feature", "System resource usage is within limits")
def test_resource_usage():
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


@when("I check system resource usage", target_fixture="resource_info")
def check_resources():
    disk = shutil.disk_usage("/")
    disk_pct = (disk.used / disk.total) * 100

    # Memory info from /proc/meminfo (Linux).
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
        pass  # Non-Linux; skip memory check.

    return {
        "disk_pct": disk_pct,
        "mem_total_kb": mem_total,
        "mem_available_kb": mem_available,
    }


@then("disk usage is below 90 percent")
def disk_ok(resource_info):
    assert resource_info["disk_pct"] < 90, (
        f"Disk usage is {resource_info['disk_pct']:.1f}% (threshold: 90%)"
    )


@then("the system is not under memory pressure")
def memory_ok(resource_info):
    if resource_info["mem_total_kb"] == 0:
        pytest.skip("Memory info not available (non-Linux host)")
    available_pct = (resource_info["mem_available_kb"] / resource_info["mem_total_kb"]) * 100
    assert available_pct > 10, f"Only {available_pct:.1f}% memory available (threshold: 10%)"
