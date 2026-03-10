"""AWS EKS cluster access."""

from __future__ import annotations

import base64
from pathlib import Path

from botocore.auth import SigV4QueryAuth

from vip.cluster.kubeconfig import write_kubeconfig


def get_eks_kubeconfig(
    cluster_name: str,
    region: str,
    profile: str | None = None,
    role_arn: str | None = None,
) -> Path:
    """Generate a kubeconfig for an EKS cluster.

    Uses boto3 to:
    1. Describe the cluster (get endpoint + CA cert)
    2. Generate an EKS bearer token via STS presigned URL
    3. Write kubeconfig to a temp file

    If *role_arn* is provided, assumes that IAM role before making
    API calls (cross-account access pattern).

    Returns the path to the kubeconfig file.
    """
    import boto3

    session = boto3.Session(profile_name=profile, region_name=region)

    if role_arn:
        sts = session.client("sts")
        assumed = sts.assume_role(RoleArn=role_arn, RoleSessionName="vip-verify")
        creds = assumed["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )

    # 1. Describe cluster
    eks = session.client("eks")
    resp = eks.describe_cluster(name=cluster_name)
    cluster = resp["cluster"]
    endpoint = cluster["endpoint"]
    ca_data = cluster["certificateAuthority"]["data"]

    # 2. Generate EKS token
    token = _generate_eks_token(session, cluster_name)

    # 3. Write kubeconfig
    return write_kubeconfig(
        cluster_name=cluster_name,
        server=endpoint,
        ca_data=ca_data,
        token=token,
    )


def _generate_eks_token(session, cluster_name: str) -> str:
    """Generate an EKS bearer token using STS presigned URL.

    This is the same technique used by ``aws eks get-token`` and PTD's
    Go implementation.  The token is a base64url-encoded presigned STS
    GetCallerIdentity URL, prefixed with ``k8s-aws-v1.``.

    The presigned URL places all auth parameters in query strings (not
    headers), which is required for EKS token validation.

    The token is valid for ~60 seconds.
    """
    from botocore.awsrequest import AWSRequest

    region = session.region_name
    url = f"https://sts.{region}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15"

    # Build request with x-k8s-aws-id header (must be signed into the URL)
    request = AWSRequest(method="GET", url=url, headers={"x-k8s-aws-id": cluster_name})

    # SigV4QueryAuth puts all auth params in query string (presigned URL style)
    credentials = session.get_credentials().get_frozen_credentials()
    SigV4QueryAuth(credentials, "sts", region, expires=60).add_auth(request)

    # Base64url-encode the presigned URL (no padding)
    token_bytes = base64.urlsafe_b64encode(request.url.encode("utf-8"))
    return "k8s-aws-v1." + token_bytes.decode("utf-8").rstrip("=")
