"""Step definitions for product server health checks.

This module previously measured test-runner-local resources (disk usage,
/proc/meminfo) which reflect the machine running VIP, not the Posit product
servers.  It now queries each configured product's health endpoint directly
so that the checks measure the actual servers under test.

Note: Posit products do not expose Prometheus-style memory/CPU metrics over
HTTP in their standard API.  If your deployment fronts the products with a
metrics proxy, those checks belong in a custom extension.  The health
endpoint check performed here confirms that each product process is alive
and serving requests, which is the meaningful liveness signal available
without additional infrastructure.
"""

from __future__ import annotations

import httpx
import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_resources.feature", "All configured products respond to health checks")
def test_product_health():
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


@when("I check the health of each configured product", target_fixture="health_results")
def check_product_health(vip_config):
    """Query each configured product's health endpoint and record the result.

    Connect:         GET /__api__/server_settings  (200 = healthy)
    Workbench:       GET /health-check              (200 = healthy)
    Package Manager: GET /__api__/status            (200 = healthy)
    """
    results = []

    checks = [
        ("Connect", vip_config.connect),
        ("Workbench", vip_config.workbench),
        ("Package Manager", vip_config.package_manager),
    ]

    health_paths = {
        "Connect": "/__api__/server_settings",
        "Workbench": "/health-check",
        "Package Manager": "/__api__/status",
    }

    for name, cfg in checks:
        if not cfg.is_configured:
            continue
        path = health_paths[name]
        url = cfg.url.rstrip("/") + path
        entry = {"product": name, "url": url, "ok": False, "status": None, "error": None}
        try:
            resp = httpx.get(url, follow_redirects=True, timeout=15)
            entry["status"] = resp.status_code
            entry["ok"] = resp.status_code == 200
        except Exception as exc:
            entry["error"] = str(exc)
        results.append(entry)

    return results


@then("all products respond with a healthy status")
def all_healthy(health_results):
    failures = [r for r in health_results if not r["ok"]]
    if not failures:
        return
    lines = []
    for r in failures:
        if r["error"]:
            lines.append(f"  {r['product']} ({r['url']}): {r['error']}")
        else:
            lines.append(f"  {r['product']} ({r['url']}): HTTP {r['status']} (expected 200)")
    assert not failures, "Product health checks failed:\n" + "\n".join(lines)
