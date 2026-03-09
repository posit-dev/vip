"""Tests for AWS EKS kubeconfig generation."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

yaml = pytest.importorskip("yaml", reason="pyyaml not installed (install vip[cluster])")
pytest.importorskip("boto3", reason="boto3 not installed (install vip[cluster])")


def test_write_kubeconfig():
    """write_kubeconfig produces valid YAML with expected structure."""
    from vip.cluster.kubeconfig import write_kubeconfig

    cluster_name = "test-cluster"
    server = "https://example.com"
    ca_data = "dGVzdC1jZXJ0"  # base64-encoded "test-cert"
    token = "test-token"

    path = write_kubeconfig(cluster_name, server, ca_data, token)

    assert path.exists()
    assert path.stat().st_mode & 0o777 == 0o600

    with open(path) as f:
        config = yaml.safe_load(f)

    assert config["apiVersion"] == "v1"
    assert config["kind"] == "Config"
    assert config["current-context"] == cluster_name
    assert len(config["clusters"]) == 1
    assert config["clusters"][0]["name"] == cluster_name
    assert config["clusters"][0]["cluster"]["server"] == server
    assert config["clusters"][0]["cluster"]["certificate-authority-data"] == ca_data
    assert len(config["users"]) == 1
    assert config["users"][0]["user"]["token"] == token


def test_kubeconfig_file_permissions():
    """Kubeconfig file should be 0600."""
    from vip.cluster.kubeconfig import write_kubeconfig

    path = write_kubeconfig("test", "https://test.com", "cert", "token")

    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_generate_eks_token_format():
    """EKS token starts with k8s-aws-v1. and contains a presigned URL."""
    from vip.cluster.aws import _generate_eks_token

    mock_session = MagicMock()
    mock_session.region_name = "us-east-1"

    cluster_name = "test-cluster"

    # Mock SigV4QueryAuth to simulate presigned URL generation.
    # SigV4QueryAuth.add_auth() modifies request.url in-place to add
    # auth query params. We simulate that here.
    with patch("vip.cluster.aws.SigV4QueryAuth") as mock_auth_class:

        def mock_add_auth(request):
            request.url += (
                "&X-Amz-Algorithm=AWS4-HMAC-SHA256"
                "&X-Amz-Credential=AKID%2F20260309%2Fus-east-1%2Fsts%2Faws4_request"
                "&X-Amz-Date=20260309T000000Z"
                "&X-Amz-Expires=60"
                "&X-Amz-SignedHeaders=host%3Bx-k8s-aws-id"
                "&X-Amz-Signature=abcdef1234567890"
            )

        mock_auth_class.return_value.add_auth.side_effect = mock_add_auth

        token = _generate_eks_token(mock_session, cluster_name)

    # Verify token format
    assert token.startswith("k8s-aws-v1.")

    # Decode the base64url part
    b64_part = token.removeprefix("k8s-aws-v1.")
    padding = (4 - len(b64_part) % 4) % 4
    decoded = base64.urlsafe_b64decode(b64_part + "=" * padding).decode("utf-8")

    # Verify the decoded URL contains expected components
    assert "sts.us-east-1.amazonaws.com" in decoded
    assert "Action=GetCallerIdentity" in decoded
    assert "X-Amz-Expires=60" in decoded
    assert "X-Amz-Signature=" in decoded


def test_get_eks_kubeconfig_integration():
    """get_eks_kubeconfig integrates all components correctly."""
    from vip.cluster.aws import get_eks_kubeconfig

    cluster_name = "test-cluster"
    region = "us-west-2"

    with (
        patch("boto3.Session") as mock_session_class,
        patch("vip.cluster.aws.SigV4QueryAuth") as mock_auth_class,
    ):
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.region_name = region

        # Mock EKS client
        mock_eks = MagicMock()
        mock_session.client.return_value = mock_eks
        mock_eks.describe_cluster.return_value = {
            "cluster": {
                "endpoint": "https://example.eks.amazonaws.com",
                "certificateAuthority": {"data": "dGVzdC1jZXJ0"},
            }
        }

        # Mock SigV4QueryAuth to simulate presigning
        def mock_add_auth(request):
            request.url += "&X-Amz-Signature=test"

        mock_auth_class.return_value.add_auth.side_effect = mock_add_auth

        path = get_eks_kubeconfig(cluster_name, region, profile=None)

    assert path.exists()
    with open(path) as f:
        config = yaml.safe_load(f)

    assert config["clusters"][0]["cluster"]["server"] == "https://example.eks.amazonaws.com"
    assert config["clusters"][0]["cluster"]["certificate-authority-data"] == "dGVzdC1jZXJ0"
    assert config["users"][0]["user"]["token"].startswith("k8s-aws-v1.")
