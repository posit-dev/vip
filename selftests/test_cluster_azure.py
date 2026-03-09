"""Tests for Azure AKS kubeconfig generation."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("azure.identity", reason="azure SDK not installed (install vip[cluster])")


def test_get_aks_kubeconfig():
    """Test AKS kubeconfig generation with mocked Azure SDK."""
    from vip.cluster.azure import get_aks_kubeconfig

    # Mock Azure SDK components
    mock_credential = MagicMock()
    mock_client = MagicMock()
    mock_result = MagicMock()

    # Sample kubeconfig content
    kubeconfig_content = b"""apiVersion: v1
kind: Config
current-context: test-cluster
clusters:
- name: test-cluster
  cluster:
    server: https://test-cluster.hcp.eastus.azmk8s.io:443
    certificate-authority-data: dGVzdC1jZXJ0
contexts:
- name: test-cluster
  context:
    cluster: test-cluster
    user: test-cluster
users:
- name: test-cluster
  user:
    token: test-token
"""
    mock_result.kubeconfigs = [MagicMock(value=kubeconfig_content)]
    mock_client.managed_clusters.list_cluster_user_credentials.return_value = mock_result

    with (
        patch("azure.identity.DefaultAzureCredential", return_value=mock_credential),
        patch("azure.mgmt.containerservice.ContainerServiceClient", return_value=mock_client),
    ):
        # Call the function
        path = get_aks_kubeconfig(
            cluster_name="test-cluster",
            resource_group="test-rg",
            subscription_id="test-sub-id",
        )

    # Verify the result
    assert path.exists()
    assert path.name == "config"
    assert path.read_bytes() == kubeconfig_content

    # Verify Azure SDK was called correctly
    mock_client.managed_clusters.list_cluster_user_credentials.assert_called_once_with(
        "test-rg", "test-cluster"
    )


def test_aks_kubeconfig_permissions():
    """Test that kubeconfig files are written with secure permissions."""
    from vip.cluster.azure import get_aks_kubeconfig

    # Mock Azure SDK
    mock_credential = MagicMock()
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.kubeconfigs = [MagicMock(value=b"test-kubeconfig")]
    mock_client.managed_clusters.list_cluster_user_credentials.return_value = mock_result

    with (
        patch("azure.identity.DefaultAzureCredential", return_value=mock_credential),
        patch("azure.mgmt.containerservice.ContainerServiceClient", return_value=mock_client),
    ):
        # Call the function
        path = get_aks_kubeconfig(
            cluster_name="test-cluster",
            resource_group="test-rg",
            subscription_id="test-sub-id",
        )

    # Verify file permissions (0600)
    stat_result = os.stat(path)
    perms = stat_result.st_mode & 0o777
    assert perms == 0o600, f"Expected 0o600, got {oct(perms)}"


def test_aks_kubeconfig_no_credentials():
    """Test error handling when no kubeconfig is returned."""
    from vip.cluster.azure import get_aks_kubeconfig

    # Mock Azure SDK to return empty kubeconfigs
    mock_credential = MagicMock()
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.kubeconfigs = []
    mock_client.managed_clusters.list_cluster_user_credentials.return_value = mock_result

    with (
        patch("azure.identity.DefaultAzureCredential", return_value=mock_credential),
        patch("azure.mgmt.containerservice.ContainerServiceClient", return_value=mock_client),
    ):
        # Verify error is raised
        with pytest.raises(ValueError, match="No kubeconfig returned for cluster test-cluster"):
            get_aks_kubeconfig(
                cluster_name="test-cluster",
                resource_group="test-rg",
                subscription_id="test-sub-id",
            )
