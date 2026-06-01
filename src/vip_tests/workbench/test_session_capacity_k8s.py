"""Step definitions for Kubernetes session capacity tests.

These tests require:
- A running Kubernetes cluster with Workbench (Launcher + Kubernetes plugin)
- ``[workbench.kubernetes]`` section in vip.toml with ``enabled = true``
- Ambient cluster credentials (kubeconfig / in-cluster service account)

All scenarios skip cleanly when ``[workbench.kubernetes]`` is absent or
``enabled = false``.  No cluster state is mutated — VIP is a read-only
observer.

Browser-driven session launching uses the same Playwright helpers as
``test_session_capacity.py``.  Kubernetes-side assertions use the
``KubernetesClient`` (read-only API calls via the ``kubernetes`` SDK).
"""

from __future__ import annotations

import time

import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import given, scenarios, then, when

from vip.clients.kubernetes import KubernetesClient
from vip_tests.workbench.conftest import (
    TIMEOUT_DIALOG,
    TIMEOUT_QUICK,
    _quit_vip_sessions_via_cookies,
    wait_for_session_active,
)
from vip_tests.workbench.pages import Homepage, NewSessionDialog

scenarios("test_session_capacity_k8s.feature")

_SESSION_PREFIX = f"_vip_k8s_{int(time.time())}_"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NODE_SCALE_POLL_SECONDS = 10
_NODE_SCALE_TIMEOUT_SECONDS = 300  # 5 minutes for a node to appear


def _launch_session(page: Page, session_name: str, profile: str | None = None) -> None:
    """Open the New Session dialog and launch with an optional resource profile."""
    page.locator(Homepage.NEW_SESSION_BUTTON).first.click(timeout=TIMEOUT_DIALOG)

    dialog = page.locator(NewSessionDialog.DIALOG)
    expect(dialog.locator(NewSessionDialog.TITLE)).to_have_text(
        "New Session", timeout=TIMEOUT_DIALOG
    )

    rstudio_tab = dialog.get_by_role("tab", name="RStudio")
    if rstudio_tab.count() > 0:
        rstudio_tab.first.click(timeout=TIMEOUT_QUICK)

    if profile is not None:
        profile_dropdown = page.locator(NewSessionDialog.RESOURCE_PROFILE)
        if profile_dropdown.is_visible(timeout=TIMEOUT_QUICK):
            tag = profile_dropdown.evaluate("el => el.tagName.toLowerCase()")
            if tag == "select":
                profile_dropdown.select_option(label=profile)
            else:
                profile_dropdown.click()
                page.wait_for_timeout(500)
                option = page.locator(f"[role='option']:has-text('{profile}')").first
                option.click(timeout=TIMEOUT_QUICK)
        else:
            pytest.skip(f"Resource profile dropdown not available; cannot select '{profile}'")

    page.fill(NewSessionDialog.SESSION_NAME, session_name)

    checkbox = page.locator(NewSessionDialog.JOIN_CHECKBOX)
    if checkbox.is_visible() and checkbox.is_checked():
        checkbox.click()

    page.locator(NewSessionDialog.LAUNCH_BUTTON).click(timeout=TIMEOUT_QUICK)
    expect(dialog).to_be_hidden(timeout=TIMEOUT_DIALOG)


def _cleanup_sessions(page: Page, workbench_base_url: str, *, insecure: bool, ca_bundle) -> None:
    try:
        cookies = {c["name"]: c["value"] for c in page.context.cookies()}
    except Exception:
        return
    if not cookies:
        return
    _quit_vip_sessions_via_cookies(
        workbench_base_url, cookies, insecure=insecure, ca_bundle=ca_bundle
    )


def _find_session_pod(k8s: KubernetesClient, session_name: str) -> dict | None:
    """Return the running pod metadata dict for *session_name*, or None."""
    for pod in k8s.running_session_pods():
        if session_name in pod["name"]:
            return pod
    return None


def _parse_cpu_cores(cpu_str: str) -> float:
    """Convert a Kubernetes CPU string (e.g. '500m', '2') to float cores."""
    if cpu_str.endswith("m"):
        return float(cpu_str[:-1]) / 1000.0
    return float(cpu_str)


def _parse_memory_gib(mem_str: str) -> float:
    """Convert a Kubernetes memory string to GiB (supports Ki, Mi, Gi, plain bytes)."""
    if mem_str.endswith("Gi"):
        return float(mem_str[:-2])
    if mem_str.endswith("Mi"):
        return float(mem_str[:-2]) / 1024.0
    if mem_str.endswith("Ki"):
        return float(mem_str[:-2]) / (1024.0 * 1024.0)
    return float(mem_str) / (1024.0**3)


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------

# NOTE: "@given("Workbench is accessible and I am logged in")" is defined in
# src/vip_tests/workbench/conftest.py and resolved from the session-wide step
# registry — no re-declaration needed here.


@given("the Kubernetes cluster is configured", target_fixture="k8s_client")
def k8s_cluster_configured(vip_config) -> KubernetesClient:
    k8s_cfg = vip_config.workbench.kubernetes
    if not k8s_cfg.is_configured:
        pytest.skip("workbench.kubernetes is not configured (set enabled = true in vip.toml)")
    try:
        return KubernetesClient(namespace=k8s_cfg.namespace)
    except RuntimeError as exc:
        pytest.skip(str(exc))


@given("a maximum session count is configured")
def max_session_count_configured(vip_config):
    if vip_config.workbench.kubernetes.max_sessions is None:
        pytest.skip("workbench.kubernetes.max_sessions is not set in vip.toml")


@given("node-pool-to-profile mappings are configured")
def node_pool_profiles_configured(vip_config):
    if not vip_config.workbench.kubernetes.node_pool_profiles:
        pytest.skip("workbench.kubernetes.node_pool_profiles is not configured in vip.toml")


@given("resource limit expectations are configured")
def resource_limits_configured(vip_config):
    k8s_cfg = vip_config.workbench.kubernetes
    if not k8s_cfg.profile_cpu_limit and not k8s_cfg.profile_memory_limit_gib:
        pytest.skip(
            "workbench.kubernetes.profile_cpu_limit / profile_memory_limit_gib "
            "are not configured in vip.toml"
        )


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when("I record the current node count", target_fixture="initial_node_count")
def record_node_count(k8s_client: KubernetesClient) -> int:
    return k8s_client.node_count()


@when(
    "I launch sessions until the current node capacity is full",
    target_fixture="launched_sessions",
)
def launch_to_fill_capacity(page: Page, vip_config, k8s_client: KubernetesClient) -> list[dict]:
    session_count = vip_config.workbench.session_count
    sessions = []
    for i in range(session_count):
        name = f"{_SESSION_PREFIX}fill_{i}"
        _launch_session(page, name)
        sessions.append({"name": name, "profile": None})
    return sessions


@when(
    "I launch sessions in quick succession to trigger autoscaling",
    target_fixture="launched_sessions",
)
def launch_quick_succession(page: Page, vip_config) -> list[dict]:
    count = max(vip_config.workbench.session_count, 3)
    sessions = []
    for i in range(count):
        name = f"{_SESSION_PREFIX}quick_{i}"
        _launch_session(page, name)
        sessions.append({"name": name, "profile": None})
    return sessions


@when(
    "I launch sessions up to the configured maximum",
    target_fixture="launched_sessions",
)
def launch_up_to_max(page: Page, vip_config) -> list[dict]:
    max_sessions = vip_config.workbench.kubernetes.max_sessions
    sessions = []
    for i in range(max_sessions):
        name = f"{_SESSION_PREFIX}max_{i}"
        _launch_session(page, name)
        sessions.append({"name": name, "profile": None})
    return sessions


@when("I launch multiple sessions concurrently", target_fixture="launched_sessions")
def launch_concurrently(page: Page, vip_config) -> list[dict]:
    count = vip_config.workbench.session_count
    sessions = []
    for i in range(count):
        name = f"{_SESSION_PREFIX}conc_{i}"
        _launch_session(page, name)
        sessions.append({"name": name, "profile": None})
    return sessions


@when(
    "I launch a session with a profiled resource profile",
    target_fixture="launched_sessions",
)
def launch_profiled_session(page: Page, vip_config) -> list[dict]:
    profile_map = vip_config.workbench.kubernetes.node_pool_profiles
    profile = next(iter(profile_map.values()))
    name = f"{_SESSION_PREFIX}prof_0"
    _launch_session(page, name, profile=profile)
    return [{"name": name, "profile": profile}]


@when(
    "I launch a session with a resource-limited profile",
    target_fixture="launched_sessions",
)
def launch_limited_session(page: Page, vip_config) -> list[dict]:
    k8s_cfg = vip_config.workbench.kubernetes
    profiles = list(k8s_cfg.profile_cpu_limit.keys()) or list(
        k8s_cfg.profile_memory_limit_gib.keys()
    )
    profile = profiles[0] if profiles else None
    name = f"{_SESSION_PREFIX}lim_0"
    _launch_session(page, name, profile=profile)
    return [{"name": name, "profile": profile}]


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the autoscaler adds at least one new node")
def autoscaler_adds_node(k8s_client: KubernetesClient, initial_node_count: int):
    deadline = time.monotonic() + _NODE_SCALE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        current = k8s_client.node_count()
        if current > initial_node_count:
            return
        time.sleep(_NODE_SCALE_POLL_SECONDS)
    pytest.fail(
        f"Autoscaler did not add a node within {_NODE_SCALE_TIMEOUT_SECONDS}s. "
        f"Initial node count: {initial_node_count}, current: {k8s_client.node_count()}"
    )


@then("all launched sessions reach Active state")
def k8s_all_sessions_active(launched_sessions: list[dict], page: Page):
    failures = []
    for session in launched_sessions:
        try:
            wait_for_session_active(page, session["name"])
        except AssertionError as exc:
            failures.append(f"{session['name']}: {exc}")
    if failures:
        pytest.fail("Sessions did not reach Active state:\n" + "\n".join(failures))


@then("the session pod runs on a node in the expected node pool")
def pod_on_expected_node_pool(
    launched_sessions: list[dict], k8s_client: KubernetesClient, vip_config
):
    profile_map = vip_config.workbench.kubernetes.node_pool_profiles
    profile_to_pool = {v: k for k, v in profile_map.items()}

    for session in launched_sessions:
        profile = session.get("profile")
        expected_pool = profile_to_pool.get(profile) if profile else None
        if expected_pool is None:
            continue
        pod = _find_session_pod(k8s_client, session["name"])
        if pod is None:
            pytest.fail(f"No running pod found for session '{session['name']}'")
        actual_pool = k8s_client.pod_node_pool(pod["name"])
        assert actual_pool == expected_pool, (
            f"Session '{session['name']}' (profile '{profile}') landed on pool "
            f"'{actual_pool}', expected '{expected_pool}'"
        )


@then("the session pod has the expected CPU and memory limits")
def pod_has_expected_limits(
    launched_sessions: list[dict], k8s_client: KubernetesClient, vip_config
):
    k8s_cfg = vip_config.workbench.kubernetes
    for session in launched_sessions:
        profile = session.get("profile")
        pod = _find_session_pod(k8s_client, session["name"])
        if pod is None:
            pytest.fail(f"No running pod found for session '{session['name']}'")
        limits = k8s_client.pod_resource_limits(pod["name"])

        if profile and profile in k8s_cfg.profile_cpu_limit:
            expected_cpu = k8s_cfg.profile_cpu_limit[profile]
            actual_cpu = _parse_cpu_cores(limits.get("cpu", "0"))
            assert abs(actual_cpu - expected_cpu) < 0.05, (
                f"CPU limit for '{session['name']}' (profile '{profile}'): "
                f"expected {expected_cpu} cores, got {actual_cpu} cores"
            )

        if profile and profile in k8s_cfg.profile_memory_limit_gib:
            expected_mem = k8s_cfg.profile_memory_limit_gib[profile]
            actual_mem = _parse_memory_gib(limits.get("memory", "0"))
            assert abs(actual_mem - expected_mem) < 0.1, (
                f"Memory limit for '{session['name']}' (profile '{profile}'): "
                f"expected {expected_mem} GiB, got {actual_mem:.2f} GiB"
            )


@then("I clean up all launched sessions")
def cleanup_k8s_sessions(
    launched_sessions: list[dict], page: Page, workbench_url: str, vip_config
):
    _cleanup_sessions(
        page, workbench_url, insecure=vip_config.insecure, ca_bundle=vip_config.ca_bundle
    )
    for session in launched_sessions:
        row = page.locator(Homepage.session_row(session["name"]))
        try:
            expect(row).to_be_hidden(timeout=TIMEOUT_DIALOG)
        except Exception:
            pass
