"""Azure AKS cluster access."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def get_aks_kubeconfig(
    cluster_name: str,
    resource_group: str,
    subscription_id: str,
) -> Path:
    """Generate a kubeconfig for an AKS cluster.

    Uses Azure SDK to call list_cluster_user_credentials which
    returns a complete kubeconfig YAML.

    Args:
        cluster_name: Name of the AKS cluster
        resource_group: Azure resource group containing the cluster
        subscription_id: Azure subscription ID

    Returns:
        Path to the kubeconfig file (written to temp directory)
    """
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.containerservice import ContainerServiceClient

    credential = DefaultAzureCredential()
    client = ContainerServiceClient(credential, subscription_id)

    result = client.managed_clusters.list_cluster_user_credentials(resource_group, cluster_name)

    # The response contains kubeconfigs as bytes
    if not result.kubeconfigs or not result.kubeconfigs[0].value:
        msg = f"No kubeconfig returned for cluster {cluster_name}"
        raise ValueError(msg)

    kubeconfig_bytes = result.kubeconfigs[0].value

    # Write to temp file with secure permissions
    tmpdir = tempfile.mkdtemp(prefix="vip-kube-")
    os.chmod(tmpdir, 0o700)
    path = Path(tmpdir) / "config"
    path.write_bytes(kubeconfig_bytes)
    os.chmod(path, 0o600)
    return path
