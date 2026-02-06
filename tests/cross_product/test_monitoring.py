"""Step definitions for monitoring / logging checks."""

from __future__ import annotations

import httpx
import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_monitoring.feature", "Monitoring is configured")
def test_monitoring_configured():
    pass


@given("monitoring is enabled in vip.toml")
def monitoring_enabled(vip_config):
    if not vip_config.monitoring_enabled:
        pytest.skip("Monitoring is not enabled in vip.toml")


@when("I check product health endpoints", target_fixture="health_results")
def check_health(vip_config):
    results = []
    products = {
        "connect": vip_config.connect,
        "workbench": vip_config.workbench,
        "package_manager": vip_config.package_manager,
    }
    health_paths = {
        "connect": "/__api__/v1/server_settings",
        "workbench": "/health-check",
        "package_manager": "/__api__/status",
    }
    for name, cfg in products.items():
        if not cfg.is_configured:
            continue
        url = f"{cfg.url}{health_paths[name]}"
        try:
            resp = httpx.get(url, timeout=15)
            results.append(
                {
                    "product": name,
                    "status": resp.status_code,
                    "ok": resp.status_code < 400,
                }
            )
        except Exception as exc:
            results.append({"product": name, "status": None, "ok": False, "error": str(exc)})
    return results


@then("all configured products respond to health checks")
def all_healthy(health_results):
    assert health_results, "No products configured to check"
    failures = [r for r in health_results if not r["ok"]]
    assert not failures, f"Health check failures: {failures}"
