"""Step definitions for concurrent request load tests.

These tests fire N simultaneous authenticated API requests against a single
endpoint per product, measuring burst throughput and p95 response time.
All requests share the same credential — this tests server capacity under
concurrent request load, not multi-user session isolation.

For multi-endpoint session simulation, see ``test_user_simulation.py``.
For true multi-user testing with unique credentials, see issue #125.
"""

from __future__ import annotations

import pytest
from pytest_bdd import parsers, scenarios, then, when

from vip.load_engine import run_load_test

scenarios("test_load.feature")


def _check_user_count(users: int, performance_config) -> None:
    """Skip if this user count is not in the configured list."""
    if users not in performance_config.load_user_counts:
        pytest.skip(
            f"{users} users not in load_user_counts ({performance_config.load_user_counts})"
        )


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when(
    parsers.parse("I run a load test with {users:d} concurrent users against Connect"),
    target_fixture="load_test_result",
)
def load_test_connect(users, vip_config, performance_config):
    _check_user_count(users, performance_config)
    if not vip_config.connect.api_key:
        pytest.skip("Connect API key is not configured")
    url = f"{vip_config.connect.url}/__api__/v1/content"
    headers = {"Authorization": f"Key {vip_config.connect.api_key}"}
    return run_load_test(url, headers, users, performance_config)


@when(
    parsers.parse("I run a load test with {users:d} concurrent users against Workbench"),
    target_fixture="load_test_result",
)
def load_test_workbench(users, vip_config, performance_config):
    _check_user_count(users, performance_config)
    if not vip_config.workbench.api_key:
        pytest.skip("Workbench API key is not configured")
    url = f"{vip_config.workbench.url}/api/server/settings"
    headers = {"Authorization": f"Key {vip_config.workbench.api_key}"}
    return run_load_test(url, headers, users, performance_config)


@when(
    parsers.parse("I run a load test with {users:d} concurrent users against Package Manager"),
    target_fixture="load_test_result",
)
def load_test_pm(users, vip_config, performance_config):
    _check_user_count(users, performance_config)
    if not vip_config.package_manager.token:
        pytest.skip("Package Manager token is not configured")
    url = f"{vip_config.package_manager.url}/__api__/repos"
    headers = {"Authorization": f"Bearer {vip_config.package_manager.token}"}
    return run_load_test(url, headers, users, performance_config)


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then("the load test success rate is at least the configured threshold")
def load_success_rate(load_test_result, performance_config):
    threshold = performance_config.load_success_rate_threshold
    rate = 1.0 - load_test_result.failure_rate
    assert rate >= threshold, (
        f"Load test success rate was {rate:.0%} "
        f"({load_test_result.successes}/{load_test_result.total} succeeded, "
        f"threshold: {threshold:.0%})"
    )


@then("the load test p95 response time is within the configured threshold")
def load_p95_response_time(load_test_result, performance_config):
    threshold = performance_config.p95_response_time
    p95 = load_test_result.p95_response_time
    assert p95 < threshold, f"Load test p95 response time was {p95:.2f}s (threshold: {threshold}s)"
