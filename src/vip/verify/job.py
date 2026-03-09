"""Kubernetes Job management for VIP verification."""

from __future__ import annotations

import json
import subprocess
import sys
import time

VIP_SECRET_NAME = "vip-test-credentials"


def create_config_map(
    name: str,
    namespace: str,
    vip_config: str,
) -> None:
    """Create a ConfigMap containing vip.toml."""
    # Build ConfigMap spec as JSON (prevents YAML injection)
    spec = {
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
        "data": {"vip.toml": vip_config},
    }
    _kubectl_apply(json.dumps(spec), namespace)


def create_job(
    name: str,
    namespace: str,
    config_map_name: str,
    image: str = "ghcr.io/posit-dev/vip:latest",
    categories: str = "",
    interactive_auth: bool = False,
    timeout_seconds: int = 840,  # 14 minutes (leave 60s buffer from 15min default)
) -> None:
    """Create a K8s Job that runs VIP tests."""
    # Build pytest args
    pytest_args = ["-v", "--tb=short"]
    if categories:
        pytest_args.extend(["-m", categories])

    # Build env vars from Secret
    env_vars = []

    if interactive_auth:
        # Interactive auth: inject API tokens from Secret
        for key in ["VIP_CONNECT_API_KEY", "VIP_WORKBENCH_API_KEY", "VIP_PM_TOKEN"]:
            env_vars.append(
                {
                    "name": key,
                    "valueFrom": {
                        "secretKeyRef": {"name": VIP_SECRET_NAME, "key": key, "optional": True}
                    },
                }
            )
    else:
        # Keycloak: inject username/password from Secret
        env_vars.append(
            {
                "name": "VIP_TEST_USERNAME",
                "valueFrom": {
                    "secretKeyRef": {"name": VIP_SECRET_NAME, "key": "username", "optional": True}
                },
            }
        )
        env_vars.append(
            {
                "name": "VIP_TEST_PASSWORD",
                "valueFrom": {
                    "secretKeyRef": {"name": VIP_SECRET_NAME, "key": "password", "optional": True}
                },
            }
        )

    # Build Job spec as JSON
    spec = {
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
                "spec": {
                    "restartPolicy": "Never",
                    "containers": [
                        {
                            "name": "vip",
                            "image": image,
                            "args": pytest_args,
                            "env": env_vars,
                            "volumeMounts": [
                                {
                                    "name": "config",
                                    "mountPath": "/app/vip.toml",
                                    "subPath": "vip.toml",
                                }
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "config",
                            "configMap": {"name": config_map_name},
                        }
                    ],
                },
            },
        },
    }
    _kubectl_apply(json.dumps(spec), namespace)


def stream_logs(job_name: str, namespace: str, timeout: int = 300) -> None:
    """Stream pod logs from the Job to stdout."""
    # Wait for pod to be created
    label = f"batch.kubernetes.io/job-name={job_name}"

    deadline = time.monotonic() + min(timeout // 4, 300)
    pod_name = None
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "pods",
                "-n",
                namespace,
                "-l",
                label,
                "-o",
                "jsonpath={.items[0].metadata.name}",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            pod_name = result.stdout.strip()
            break
        time.sleep(2)

    if not pod_name:
        print("Warning: Could not find pod for job", file=sys.stderr)
        return

    # Wait for pod to be running or completed
    deadline = time.monotonic() + min(timeout // 4, 300)
    while time.monotonic() < deadline:
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
        )
        phase = result.stdout.strip()
        if phase in ("Running", "Succeeded", "Failed"):
            break

        # Check for image pull errors
        result = subprocess.run(
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
        )
        reason = result.stdout.strip()
        if reason in ("ImagePullBackOff", "ErrImagePull"):
            print(f"Error: Image pull failed ({reason})", file=sys.stderr)
            return

        time.sleep(2)

    # Stream logs
    subprocess.run(
        ["kubectl", "logs", "-f", pod_name, "-n", namespace],
    )


def wait_for_job(job_name: str, namespace: str, timeout: int = 900) -> bool:
    """Wait for Job to complete. Returns True if successful."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "job",
                job_name,
                "-n",
                namespace,
                "-o",
                "jsonpath={.status.conditions[?(@.type=='Complete')].status},"
                "{.status.conditions[?(@.type=='Failed')].status}",
            ],
            capture_output=True,
            text=True,
        )
        parts = result.stdout.strip().split(",")
        complete = parts[0] if len(parts) > 0 else ""
        failed = parts[1] if len(parts) > 1 else ""

        if complete == "True":
            return True
        if failed == "True":
            return False

        time.sleep(5)

    print(f"Warning: Job {job_name} did not complete within {timeout}s", file=sys.stderr)
    return False


def cleanup(job_name: str, config_map_name: str, namespace: str) -> None:
    """Delete Job and ConfigMap."""
    for resource_type, name in [("job", job_name), ("configmap", config_map_name)]:
        subprocess.run(
            ["kubectl", "delete", resource_type, name, "-n", namespace, "--ignore-not-found"],
            capture_output=True,
        )


def _kubectl_apply(manifest_json: str, namespace: str) -> None:
    """Apply a JSON manifest via kubectl."""
    result = subprocess.run(
        ["kubectl", "apply", "-f", "-", "-n", namespace],
        input=manifest_json,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"kubectl apply failed: {result.stderr}")
