"""Step definitions for realistic user simulation tests.

These tests use Locust to simulate concurrent users performing realistic
multi-endpoint sessions against each product: browsing content, checking
settings, listing sessions, fetching package indexes, etc.

Unlike the burst load tests (test_load.py) which fire N identical requests,
these tests model real user behavior with weighted task frequencies and
think-time between requests.

Requires the ``vip[load]`` extra (locust).
"""

from __future__ import annotations

import pytest
from pytest_bdd import parsers, scenarios, then, when

from vip.load_engine import run_user_simulation

scenarios("test_user_simulation.feature")


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


@when(
    parsers.parse("I simulate {users:d} concurrent users on Connect"),
    target_fixture="simulation_result",
)
def simulate_connect(users, vip_config, performance_config):
    if not vip_config.connect.api_key:
        pytest.skip("Connect API key is not configured")
    return run_user_simulation(
        host=vip_config.connect.url,
        user_class_name="connect",
        users=users,
        config=performance_config,
        credentials={"api_key": vip_config.connect.api_key},
    )


@when(
    parsers.parse("I simulate {users:d} concurrent users on Workbench"),
    target_fixture="simulation_result",
)
def simulate_workbench(users, vip_config, performance_config):
    if not vip_config.workbench.api_key:
        pytest.skip("Workbench API key is not configured")
    return run_user_simulation(
        host=vip_config.workbench.url,
        user_class_name="workbench",
        users=users,
        config=performance_config,
        credentials={"api_key": vip_config.workbench.api_key},
    )


@when(
    parsers.parse("I simulate {users:d} concurrent users on Package Manager"),
    target_fixture="simulation_result",
)
def simulate_pm(users, vip_config, performance_config):
    if not vip_config.package_manager.url:
        pytest.skip("Package Manager URL is not configured")
    token = vip_config.package_manager.token or ""
    return run_user_simulation(
        host=vip_config.package_manager.url,
        user_class_name="package_manager",
        users=users,
        config=performance_config,
        credentials={"token": token},
    )


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then("the simulation success rate is at least the configured threshold")
def simulation_success_rate(simulation_result, performance_config):
    threshold = performance_config.load_success_rate_threshold
    rate = 1.0 - simulation_result.failure_rate
    assert rate >= threshold, (
        f"User simulation success rate was {rate:.0%} "
        f"({simulation_result.successes}/{simulation_result.total} succeeded, "
        f"threshold: {threshold:.0%})"
    )


@then("the simulation p95 response time is within the configured threshold")
def simulation_p95(simulation_result, performance_config):
    threshold = performance_config.p95_response_time
    p95 = simulation_result.p95_response_time
    assert p95 < threshold, (
        f"User simulation p95 response time was {p95:.2f}s (threshold: {threshold}s)"
    )
