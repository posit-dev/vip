"""Cluster target resolution and validation."""

from __future__ import annotations

from vip.config import ClusterConfig


def validate_cluster_config(config: ClusterConfig) -> None:
    """Validate that cluster config has required fields for the given provider.

    Args:
        config: The cluster configuration to validate.

    Raises:
        ValueError: If the cluster configuration is invalid.
    """
    if not config.is_configured:
        raise ValueError("Cluster not configured: set provider and name in [cluster] section")
    if config.provider not in ("aws", "azure"):
        raise ValueError(
            f"Unknown cluster provider: {config.provider!r} (expected 'aws' or 'azure')"
        )
    if config.provider == "aws" and not config.region:
        raise ValueError("AWS clusters require region in [cluster] section")
    if config.provider == "azure" and not config.resource_group:
        raise ValueError("Azure clusters require resource_group in [cluster] section")
