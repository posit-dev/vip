# Plan for issue #304: Add Kubernetes autoscaling and capacity probes

## Context

The current `test_session_capacity.feature` verifies that N sessions reach Active state but doesn't probe behavior at autoscaling boundaries or verify that resource limits are enforced. A Posit customer running Kubernetes-backed Workbench UAT flagged six scenarios around autoscaling, capacity limits, and resource profile enforcement that are generic to any Posit Team on Kubernetes deployment (Launcher + Kubernetes plugin). This enhancement adds those scenarios to ensure VIP can validate Kubernetes-specific session capacity behavior.

## Architecture

This lands in the `src/vip_tests/workbench/` test suite as a new feature file (or extension to the existing `test_session_capacity.feature`). The test DSL (step definitions) will be in a corresponding `.py` file that uses two client layers:

- A new `src/vip/clients/kubernetes.py` client for read-only cluster queries (node counts, pod scheduling, resource quotas). This wraps either `kubectl` CLI calls or the `kubernetes` Python SDK.
- The existing `src/vip/clients/workbench.py` client for session launches and status checks.

Configuration will extend the `[workbench]` section in `vip.toml` with a new `[workbench.kubernetes]` block for node-pool names, per-profile pool mappings, and expected CPU/memory caps. Cluster access is **inherited from the ambient environment** (the default kubeconfig at `~/.kube/config`, the `KUBECONFIG` env var, or an in-cluster service account token) — exactly the same credentials that `kubectl` would use on that machine. No separate credential fields are stored in `vip.toml`; the user is responsible for ensuring their environment already has the appropriate access configured before running these tests.

## Components

**New files:**
- `src/vip/clients/kubernetes.py` — read-only Kubernetes client (node counts, pod scheduling info, resource quotas)
- `src/vip_tests/workbench/test_session_capacity_k8s.feature` — six Gherkin scenarios for autoscaling, capacity limits, and resource profile routing
- `src/vip_tests/workbench/test_session_capacity_k8s.py` — step definitions for the new scenarios

**Modified files:**
- `src/vip/config.py` — add `WorkbenchKubernetesConfig` dataclass and wire it into the main `WorkbenchConfig`
- `src/vip_tests/conftest.py` — add `kubernetes_client` fixture (auto-skip when no K8s config present)
- `selftests/config/test_workbench_kubernetes_config.py` — config loading test for the new TOML block

## Verification

A reviewer can confirm the plan structure is sound by:

1. Reviewing the proposed feature file scenarios against the issue's six use cases.
2. Confirming the config schema supports the needed fields (node-pool names, per-profile mappings, resource caps).
3. Checking that the Kubernetes client interface is read-only (no cluster mutations).
4. Verifying auto-skip behavior when `[workbench.kubernetes]` is absent.

End-to-end verification requires a live Kubernetes cluster with Workbench:

```bash
# Add [workbench.kubernetes] block to vip.toml with node-pool config
uv run vip verify --config vip.toml --categories workbench -- -k session_capacity_k8s -v
```

Expected: all six scenarios pass (or skip cleanly if no cluster config).

## Decisions

- `src/vip/clients/kubernetes.py` will use the **`kubernetes` Python SDK**. The SDK calls `load_kube_config()` / `load_incluster_config()`, which reads the same ambient kubeconfig (`~/.kube/config`, `KUBECONFIG`, or in-cluster service account) that `kubectl` uses — no separate credential setup required.
- The "quick succession" scenarios will use **asyncio** for concurrent session launches.
- The new scenarios will live in a **separate `test_session_capacity_k8s.feature`** file, keeping the Kubernetes-specific tests clearly distinct from the generic capacity tests.

## Out of scope

- Mutation of cluster state — VIP remains a read-only observer; it does not adjust node pools or quotas.
- Support for non-Kubernetes launchers — these scenarios are specific to the Kubernetes launcher plugin.
- Autoscaler-specific configuration — VIP assumes the cluster has an autoscaler configured; it does not install or configure one.
- Performance benchmarking — the scenarios verify correctness (one node added, one session landed) but do not measure scale-up latency or throughput.
