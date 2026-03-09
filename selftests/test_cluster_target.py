"""Tests for vip.cluster.target module."""

from __future__ import annotations

import pytest

from vip.cluster.target import validate_cluster_config
from vip.config import ClusterConfig


class TestValidateClusterConfig:
    def test_valid_aws_config(self):
        config = ClusterConfig(
            provider="aws",
            name="test-cluster",
            region="us-east-1",
        )
        # Should not raise
        validate_cluster_config(config)

    def test_valid_azure_config(self):
        config = ClusterConfig(
            provider="azure",
            name="aks-cluster",
            resource_group="posit-rg",
        )
        # Should not raise
        validate_cluster_config(config)

    def test_raises_on_missing_provider(self):
        config = ClusterConfig(name="test-cluster")
        with pytest.raises(ValueError, match="Cluster not configured"):
            validate_cluster_config(config)

    def test_raises_on_missing_name(self):
        config = ClusterConfig(provider="aws")
        with pytest.raises(ValueError, match="Cluster not configured"):
            validate_cluster_config(config)

    def test_raises_on_unknown_provider(self):
        config = ClusterConfig(provider="gcp", name="test-cluster")
        with pytest.raises(ValueError, match="Unknown cluster provider.*gcp"):
            validate_cluster_config(config)

    def test_raises_on_missing_aws_region(self):
        config = ClusterConfig(provider="aws", name="test-cluster")
        with pytest.raises(ValueError, match="AWS clusters require region"):
            validate_cluster_config(config)

    def test_raises_on_missing_azure_resource_group(self):
        config = ClusterConfig(provider="azure", name="test-cluster")
        with pytest.raises(ValueError, match="Azure clusters require resource_group"):
            validate_cluster_config(config)

    def test_aws_with_all_fields(self):
        config = ClusterConfig(
            provider="aws",
            name="full-cluster",
            region="us-west-2",
            namespace="custom-namespace",
            site="secondary",
            profile="my-profile",
        )
        # Should not raise
        validate_cluster_config(config)

    def test_azure_with_all_fields(self):
        config = ClusterConfig(
            provider="azure",
            name="full-aks",
            region="westus",
            resource_group="my-rg",
            subscription_id="abc123",
            namespace="custom-namespace",
            site="secondary",
        )
        # Should not raise
        validate_cluster_config(config)
