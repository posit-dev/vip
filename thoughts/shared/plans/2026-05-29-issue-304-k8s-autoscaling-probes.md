# Plan for issue #304: Add Kubernetes autoscaling and capacity probes

## Context

The current `test_session_capacity.feature` verifies that N sessions reach Active state but doesn't probe behavior at autoscaling boundaries or verify that resource limits are enforced. A Posit customer running Kubernetes-backed Workbench UAT flagged six scenarios around autoscaling, capacity limits, and resource profile enforcement that are generic to any Posit Team on Kubernetes deployment (Launcher + Kubernetes plugin). This enhancement adds those scenarios to ensure VIP can validate Kubernetes-specific session capacity behavior.

## Architecture

This lands in the `src/vip_tests/workbench/` test suite as a new feature file (or extension to the existing `test_session_capacity.feature`). The test DSL (step definitions) will be in a corresponding `.py` file that uses two client layers:

- A new `src/vip/clients/kubernetes.py` client for read-only cluster queries (node counts, pod scheduling, resource quotas). This wraps either `kubectl` CLI calls or the `kubernetes` Python SDK.
- The existing `src/vip/clients/workbench.py` client for session launches and status checks.

Configuration will extend the `[workbench]` section in `vip.toml` with a new `[workbench.kubernetes]` block for node-pool names, per-profile pool mappings, expected CPU/memory caps, and cluster credentials.

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

## Open questions

- **UNCONFIRMED:** Should `src/vip/clients/kubernetes.py` use `kubectl` CLI (already a VIP install dependency) or the `kubernetes` Python SDK? SDK has cleaner error handling but adds a dependency. CLI path is simpler if `kubectl` is already available from `vip cluster` commands.
- **UNCONFIRMED:** Should the "quick succession" scenarios use Python threading, asyncio, or Playwright's multi-context API for concurrent launches? Threading is simplest but may not exercise the race condition reliably.
- Should the new scenarios live in a separate `test_session_capacity_k8s.feature` or extend the existing `test_session_capacity.feature` with an `@kubernetes` tag? Separate file keeps the distinction clear.

## Out of scope

- Mutation of cluster state — VIP remains a read-only observer; it does not adjust node pools or quotas.
- Support for non-Kubernetes launchers — these scenarios are specific to the Kubernetes launcher plugin.
- Autoscaler-specific configuration — VIP assumes the cluster has an autoscaler configured; it does not install or configure one.
- Performance benchmarking — the scenarios verify correctness (one node added, one session landed) but do not measure scale-up latency or throughput.
