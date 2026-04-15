"""Kubernetes Job management for VIP verification."""

from __future__ import annotations

import json
import subprocess
import time


def create_config_map(name: str, namespace: str, vip_config_toml: str) -> None:
    """Create a K8s ConfigMap with the VIP config.

    Args:
        name: ConfigMap name
        namespace: Kubernetes namespace
        vip_config_toml: VIP config TOML content

    Raises:
        subprocess.CalledProcessError: If kubectl fails
    """
    config_map_spec = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "vip",
                "app.kubernetes.io/name": "vip-verify",
            },
        },
        "data": {
            "vip.toml": vip_config_toml,
        },
    }

    config_map_json = json.dumps(config_map_spec)

    cmd = ["kubectl", "apply", "-f", "-", "-n", namespace]
    subprocess.run(
        cmd,
        input=config_map_json,
        text=True,
        check=True,
        capture_output=True,
    )


def create_job(
    name: str,
    namespace: str,
    config_map_name: str,
    image: str = "ghcr.io/posit-dev/vip:latest",
    categories: str | None = None,
    filter_expr: str | None = None,
    timeout_seconds: int = 840,
    verbose: bool = False,
) -> None:
    """Create a K8s Job to run VIP tests.

    Args:
        name: Job name
        namespace: Kubernetes namespace
        config_map_name: Name of the ConfigMap containing vip.toml
        image: VIP container image
        categories: Test categories to run (pytest -m marker)
        filter_expr: Test name filter expression (pytest -k)
        timeout_seconds: Job timeout in seconds
        verbose: Show full pytest tracebacks instead of concise errors

    Raises:
        subprocess.CalledProcessError: If kubectl fails
    """
    # Build pytest command
    pytest_args = ["pytest", "--vip-config=/config/vip.toml", "-v"]
    if verbose:
        pytest_args.append("--vip-verbose")
    if categories:
        pytest_args.extend(["-m", categories])
    if filter_expr:
        pytest_args.extend(["-k", filter_expr])

    # Always mount the vip-test-credentials Secret via envFrom so that
    # credentials written by either credential path (Keycloak or interactive)
    # are available as environment variables.  optional=True means the Job
    # starts even when no Secret exists (credentials come from elsewhere).
    env_from = [
        {
            "secretRef": {
                "name": "vip-test-credentials",
                "optional": True,
            }
        }
    ]

    job_spec = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "vip",
                "app.kubernetes.io/name": "vip-verify",
            },
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": timeout_seconds,
            "template": {
                "metadata": {
                    "labels": {
                        "app.kubernetes.io/name": "vip-verify",
                    }
                },
                "spec": {
                    "restartPolicy": "Never",
                    "containers": [
                        {
                            "name": "vip",
                            "image": image,
                            "command": ["uv", "run"],
                            "args": pytest_args,
                            "volumeMounts": [
                                {
                                    "name": "config",
                                    "mountPath": "/config",
                                    "readOnly": True,
                                }
                            ],
                            "envFrom": env_from,
                        }
                    ],
                    "volumes": [
                        {
                            "name": "config",
                            "configMap": {
                                "name": config_map_name,
                            },
                        }
                    ],
                },
            },
        },
    }

    job_json = json.dumps(job_spec)

    cmd = ["kubectl", "apply", "-f", "-", "-n", namespace]
    subprocess.run(
        cmd,
        input=job_json,
        text=True,
        check=True,
        capture_output=True,
    )


def _wait_for_pod(job_name: str, namespace: str, deadline: float) -> str:
    """Wait for a pod to appear for the given job and return its name.

    Args:
        job_name: Job name
        namespace: Kubernetes namespace
        deadline: Absolute time (from time.time()) by which the pod must appear

    Raises:
        TimeoutError: If no pod is found before the deadline
    """
    while time.time() < deadline:
        cmd = [
            "kubectl",
            "get",
            "pods",
            "-n",
            namespace,
            "-l",
            f"job-name={job_name}",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

        time.sleep(2)

    raise TimeoutError(f"Pod for job {job_name} not found within deadline")


def _wait_for_pod_running(pod_name: str, namespace: str, deadline: float) -> None:
    """Wait for the pod to reach a running (or terminal) state.

    Without this, ``kubectl logs -f`` fails with
    "container is waiting to start: ContainerCreating".

    Args:
        pod_name: Pod name
        namespace: Kubernetes namespace
        deadline: Absolute time (from time.time()) by which the pod must be running

    Raises:
        RuntimeError: If the image cannot be pulled
    """
    while time.time() < deadline:
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "pod",
                pod_name,
                "-n",
                namespace,
                "-o",
                "jsonpath={.status.phase}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        phase = result.stdout.strip()
        if phase in ("Running", "Succeeded", "Failed"):
            return

        # Fast-fail on image pull errors
        reason_result = subprocess.run(
            [
                "kubectl",
                "get",
                "pod",
                pod_name,
                "-n",
                namespace,
                "-o",
                "jsonpath={.status.containerStatuses[0].state.waiting.reason}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        reason = reason_result.stdout.strip()
        if reason in ("ImagePullBackOff", "ErrImagePull"):
            raise RuntimeError(f"Image pull failed for pod {pod_name}: {reason}")

        time.sleep(2)


def stream_logs(job_name: str, namespace: str, timeout: int = 900) -> None:
    """Stream logs from the VIP Job.

    Waits for the pod to be created and running, then streams logs.

    Args:
        job_name: Job name
        namespace: Kubernetes namespace
        timeout: Timeout in seconds

    Raises:
        subprocess.CalledProcessError: If kubectl fails
        TimeoutError: If pod is not found or not running within timeout
        RuntimeError: If the pod image cannot be pulled
    """
    deadline = time.time() + timeout

    pod_name = _wait_for_pod(job_name, namespace, deadline)
    _wait_for_pod_running(pod_name, namespace, deadline)

    # Stream logs (this will block until the pod completes or fails)
    cmd = ["kubectl", "logs", "-n", namespace, "-f", pod_name]
    subprocess.run(cmd, check=False)


def wait_for_job(job_name: str, namespace: str, timeout: int = 900) -> bool:
    """Wait for the Job to complete and return success status.

    Args:
        job_name: Job name
        namespace: Kubernetes namespace
        timeout: Timeout in seconds

    Returns:
        True if the Job succeeded, False otherwise

    Raises:
        subprocess.CalledProcessError: If kubectl fails
        TimeoutError: If Job does not complete within timeout
    """
    start_time = time.time()

    while time.time() - start_time < timeout:
        cmd = [
            "kubectl",
            "get",
            "job",
            job_name,
            "-n",
            namespace,
            "-o",
            "json",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        job = json.loads(result.stdout)
        status = job.get("status", {})

        # Check if Job succeeded
        if status.get("succeeded", 0) > 0:
            return True

        # Check if Job failed
        if status.get("failed", 0) > 0:
            return False

        time.sleep(5)

    raise TimeoutError(f"Job {job_name} did not complete within {timeout}s")


def cleanup(job_name: str, config_map_name: str, namespace: str) -> None:
    """Delete the Job and ConfigMap.

    Args:
        job_name: Job name
        config_map_name: ConfigMap name
        namespace: Kubernetes namespace

    Note:
        This function does not raise errors if resources don't exist.
    """
    # Delete Job
    cmd = [
        "kubectl",
        "delete",
        "job",
        job_name,
        "-n",
        namespace,
        "--ignore-not-found",
    ]
    subprocess.run(cmd, capture_output=True, check=False)

    # Delete ConfigMap
    cmd = [
        "kubectl",
        "delete",
        "configmap",
        config_map_name,
        "-n",
        namespace,
        "--ignore-not-found",
    ]
    subprocess.run(cmd, capture_output=True, check=False)
