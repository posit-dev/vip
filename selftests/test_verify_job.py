"""Tests for vip.verify.job module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from vip.verify import job


def test_create_config_map():
    """Test ConfigMap creation with proper JSON structure."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        job.create_config_map(
            name="test-config",
            namespace="default",
            vip_config="[connect]\nurl = 'https://connect.example.com'\n",
        )

        # Verify kubectl apply was called
        assert mock_run.call_count == 1
        call_args = mock_run.call_args

        # Verify command structure
        assert call_args[0][0] == ["kubectl", "apply", "-f", "-", "-n", "default"]

        # Verify JSON input
        manifest = json.loads(call_args[1]["input"])
        assert manifest["apiVersion"] == "v1"
        assert manifest["kind"] == "ConfigMap"
        assert manifest["metadata"]["name"] == "test-config"
        assert manifest["metadata"]["namespace"] == "default"
        assert manifest["metadata"]["labels"]["app.kubernetes.io/managed-by"] == "vip"
        assert "vip.toml" in manifest["data"]


def test_create_job_keycloak_mode():
    """Test Job creation with Keycloak auth (username/password)."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        job.create_job(
            name="test-job",
            namespace="default",
            config_map_name="test-config",
            image="ghcr.io/posit-dev/vip:test",
            categories="connect",
            interactive_auth=False,
            timeout_seconds=600,
        )

        # Verify kubectl apply was called
        assert mock_run.call_count == 1
        call_args = mock_run.call_args

        # Verify JSON input
        manifest = json.loads(call_args[1]["input"])
        assert manifest["apiVersion"] == "batch/v1"
        assert manifest["kind"] == "Job"
        assert manifest["metadata"]["name"] == "test-job"
        assert manifest["spec"]["backoffLimit"] == 0
        assert manifest["spec"]["activeDeadlineSeconds"] == 600

        # Verify container spec
        container = manifest["spec"]["template"]["spec"]["containers"][0]
        assert container["image"] == "ghcr.io/posit-dev/vip:test"
        assert container["args"] == ["-v", "--tb=short", "-m", "connect"]

        # Verify Keycloak env vars
        env_names = [e["name"] for e in container["env"]]
        assert "VIP_TEST_USERNAME" in env_names
        assert "VIP_TEST_PASSWORD" in env_names
        assert "VIP_CONNECT_API_KEY" not in env_names

        # Verify username env var structure
        username_env = next(e for e in container["env"] if e["name"] == "VIP_TEST_USERNAME")
        assert username_env["valueFrom"]["secretKeyRef"]["name"] == "vip-test-credentials"
        assert username_env["valueFrom"]["secretKeyRef"]["key"] == "username"


def test_create_job_interactive_mode():
    """Test Job creation with interactive auth (API tokens)."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        job.create_job(
            name="test-job",
            namespace="default",
            config_map_name="test-config",
            interactive_auth=True,
        )

        # Verify kubectl apply was called
        call_args = mock_run.call_args
        manifest = json.loads(call_args[1]["input"])

        # Verify container spec
        container = manifest["spec"]["template"]["spec"]["containers"][0]

        # Verify interactive auth env vars
        env_names = [e["name"] for e in container["env"]]
        assert "VIP_CONNECT_API_KEY" in env_names
        assert "VIP_WORKBENCH_API_KEY" in env_names
        assert "VIP_PM_TOKEN" in env_names
        assert "VIP_TEST_USERNAME" not in env_names
        assert "VIP_TEST_PASSWORD" not in env_names

        # Verify API key env var structure (with optional flag)
        connect_key_env = next(e for e in container["env"] if e["name"] == "VIP_CONNECT_API_KEY")
        assert connect_key_env["valueFrom"]["secretKeyRef"]["name"] == "vip-test-credentials"
        assert connect_key_env["valueFrom"]["secretKeyRef"]["key"] == "VIP_CONNECT_API_KEY"

        # Verify Workbench key is optional
        wb_key_env = next(e for e in container["env"] if e["name"] == "VIP_WORKBENCH_API_KEY")
        assert wb_key_env["valueFrom"]["secretKeyRef"]["optional"] is True


def test_wait_for_job_complete():
    """Test waiting for Job to complete successfully."""
    with patch("subprocess.run") as mock_run, patch("time.sleep"):
        # First call returns no completion, second returns Complete=True
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=","),  # Not complete yet
            MagicMock(returncode=0, stdout="True,"),  # Complete
        ]

        result = job.wait_for_job("test-job", "default", timeout=10)

        assert result is True
        assert mock_run.call_count == 2


def test_wait_for_job_failed():
    """Test waiting for Job that fails."""
    with patch("subprocess.run") as mock_run, patch("time.sleep"):
        # First call returns no completion, second returns Failed=True
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=","),  # Not complete yet
            MagicMock(returncode=0, stdout=",True"),  # Failed
        ]

        result = job.wait_for_job("test-job", "default", timeout=10)

        assert result is False
        assert mock_run.call_count == 2


def test_wait_for_job_timeout():
    """Test waiting for Job that times out."""
    with patch("subprocess.run") as mock_run, patch("time.monotonic") as mock_time:
        # Simulate timeout by making monotonic() exceed deadline
        mock_time.side_effect = [0, 10, 20, 1000]  # Last value exceeds deadline
        mock_run.return_value = MagicMock(returncode=0, stdout=",")

        result = job.wait_for_job("test-job", "default", timeout=100)

        assert result is False


def test_cleanup():
    """Test cleanup deletes Job and ConfigMap."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        job.cleanup("test-job", "test-config", "default")

        # Verify two delete commands were called
        assert mock_run.call_count == 2

        calls = mock_run.call_args_list
        job_delete = calls[0][0][0]
        cm_delete = calls[1][0][0]

        assert job_delete == [
            "kubectl",
            "delete",
            "job",
            "test-job",
            "-n",
            "default",
            "--ignore-not-found",
        ]
        assert cm_delete == [
            "kubectl",
            "delete",
            "configmap",
            "test-config",
            "-n",
            "default",
            "--ignore-not-found",
        ]


def test_kubectl_apply_failure():
    """Test that kubectl apply failures raise RuntimeError."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="error: unable to apply manifest")

        with pytest.raises(RuntimeError, match="kubectl apply failed"):
            job._kubectl_apply('{"kind": "ConfigMap"}', "default")
