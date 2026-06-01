"""Read-only Kubernetes client for VIP Workbench capacity tests.

Uses the ``kubernetes`` Python SDK, which reads cluster credentials from the
ambient environment (``~/.kube/config``, ``KUBECONFIG`` env var, or an
in-cluster service account token) — the same source as ``kubectl``.

If the ``kubernetes`` package is not installed, all methods raise
``RuntimeError`` with a clear install hint so selftests and collection
don't fail on machines without the SDK.
"""

from __future__ import annotations

from typing import Any


def _require_sdk() -> Any:
    """Return the ``kubernetes`` module or raise with an install hint."""
    try:
        import kubernetes  # type: ignore[import-untyped]

        return kubernetes
    except ImportError as exc:
        raise RuntimeError(
            "The 'kubernetes' package is required for Kubernetes capacity tests. "
            "Install it with: uv add kubernetes"
        ) from exc


def _load_config() -> None:
    """Load kubeconfig from the ambient environment."""
    k8s = _require_sdk()
    try:
        k8s.config.load_incluster_config()
    except k8s.config.ConfigException:
        k8s.config.load_kube_config()


class KubernetesClient:
    """Minimal read-only Kubernetes wrapper for VIP session capacity probes.

    All methods are non-mutating — no cluster state is changed.
    """

    def __init__(self, namespace: str = "posit-team") -> None:
        self._namespace = namespace
        _load_config()
        k8s = _require_sdk()
        self._core = k8s.client.CoreV1Api()
        self._apps = k8s.client.AppsV1Api()

    # -- Node queries -------------------------------------------------------

    def node_count(self, *, node_pool_label: str | None = None) -> int:
        """Return the number of Ready nodes, optionally filtered by pool label.

        Parameters
        ----------
        node_pool_label:
            If given, only nodes with ``kubernetes.io/hostname`` matching this
            value (or with an ``agentpool`` / ``node-pool`` label equal to this
            value) are counted.  Pass ``None`` to count all Ready nodes.
        """
        nodes = self._core.list_node().items
        ready_nodes = []
        for node in nodes:
            conditions = node.status.conditions or []
            is_ready = any(c.type == "Ready" and c.status == "True" for c in conditions)
            if not is_ready:
                continue
            if node_pool_label is not None:
                labels: dict[str, str] = node.metadata.labels or {}
                pool = labels.get("agentpool") or labels.get("cloud.google.com/gke-nodepool") or ""
                if pool != node_pool_label:
                    continue
            ready_nodes.append(node)
        return len(ready_nodes)

    # -- Pod / session queries ----------------------------------------------

    def running_session_pods(self, *, label_selector: str = "app=rstudio") -> list[dict]:
        """Return metadata dicts for Running session pods in the namespace."""
        pods = self._core.list_namespaced_pod(
            namespace=self._namespace,
            label_selector=label_selector,
        ).items
        result = []
        for pod in pods:
            if pod.status.phase == "Running":
                labels: dict[str, str] = pod.metadata.labels or {}
                result.append(
                    {
                        "name": pod.metadata.name,
                        "node": pod.spec.node_name,
                        "labels": labels,
                    }
                )
        return result

    def pod_node_pool(self, pod_name: str) -> str:
        """Return the node-pool label value for the node hosting *pod_name*."""
        pod = self._core.read_namespaced_pod(name=pod_name, namespace=self._namespace)
        node_name = pod.spec.node_name
        node = self._core.read_node(name=node_name)
        labels: dict[str, str] = node.metadata.labels or {}
        return (
            labels.get("agentpool")
            or labels.get("cloud.google.com/gke-nodepool")
            or ""
        )

    # -- Resource quota queries --------------------------------------------

    def resource_quota(self) -> dict[str, str]:
        """Return hard limits from the first ResourceQuota in the namespace.

        Returns an empty dict when no quota is configured.
        """
        quotas = self._core.list_namespaced_resource_quota(
            namespace=self._namespace
        ).items
        if not quotas:
            return {}
        return dict(quotas[0].status.hard or {})

    def pod_resource_limits(self, pod_name: str) -> dict[str, str]:
        """Return the resource limits of the first container in *pod_name*.

        Returns an empty dict when no limits are set.
        """
        pod = self._core.read_namespaced_pod(name=pod_name, namespace=self._namespace)
        containers = pod.spec.containers or []
        if not containers:
            return {}
        limits = containers[0].resources.limits or {}
        return dict(limits)
