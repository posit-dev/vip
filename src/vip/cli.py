"""VIP command-line tools for credential management and verification."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path


def mint_connect_key(args: argparse.Namespace) -> None:
    """Launch interactive browser auth and mint a Connect API key."""
    from vip.auth import start_interactive_auth

    session = start_interactive_auth(args.url)

    if not session.api_key:
        print(json.dumps({"error": "Failed to mint API key"}), file=sys.stderr)
        sys.exit(1)

    # Output JSON with key and key_name for cleanup.
    # The key_name can be used to find the key_id via the API later.
    result = {
        "api_key": session.api_key,
        "key_name": session.key_name,
    }

    print(json.dumps(result))


def connect_to_cluster(args: argparse.Namespace) -> None:
    """Generate kubeconfig for a cluster and print the path."""
    from vip.cluster.target import validate_cluster_config
    from vip.config import load_config

    config = load_config()

    # Override cluster config from CLI args if provided
    if args.provider:
        config.cluster.provider = args.provider
    if args.cluster_name:
        config.cluster.name = args.cluster_name
    if args.region:
        config.cluster.region = args.region
    if args.resource_group:
        config.cluster.resource_group = args.resource_group
    if args.subscription_id:
        config.cluster.subscription_id = args.subscription_id
    if args.profile:
        config.cluster.profile = args.profile

    validate_cluster_config(config.cluster)

    if config.cluster.provider == "aws":
        from vip.cluster.aws import get_eks_kubeconfig

        kubeconfig_path = get_eks_kubeconfig(
            config.cluster.name,
            config.cluster.region,
            config.cluster.profile or None,
        )
    elif config.cluster.provider == "azure":
        from vip.cluster.azure import get_aks_kubeconfig

        kubeconfig_path = get_aks_kubeconfig(
            config.cluster.name,
            config.cluster.resource_group,
            config.cluster.subscription_id,
        )
    else:
        print(f"Unsupported provider: {config.cluster.provider}", file=sys.stderr)
        sys.exit(1)

    print(str(kubeconfig_path))


def run_verify(args: argparse.Namespace) -> None:
    """Main verification flow."""
    from vip.config import load_config

    config = load_config()

    # 1. Connect to cluster (if cluster is configured)
    kubeconfig_path = None
    if config.cluster.is_configured:
        from vip.cluster.target import validate_cluster_config

        validate_cluster_config(config.cluster)

        if config.cluster.provider == "aws":
            from vip.cluster.aws import get_eks_kubeconfig

            kubeconfig_path = get_eks_kubeconfig(
                config.cluster.name,
                config.cluster.region,
                config.cluster.profile or None,
            )
        elif config.cluster.provider == "azure":
            from vip.cluster.azure import get_aks_kubeconfig

            kubeconfig_path = get_aks_kubeconfig(
                config.cluster.name,
                config.cluster.resource_group,
                config.cluster.subscription_id,
            )

        os.environ["KUBECONFIG"] = str(kubeconfig_path)
        print(f"Connected to cluster: {config.cluster.name}")

    # 2. Fetch Site CR and generate vip.toml
    from vip.verify.site import fetch_site_cr, generate_vip_config

    print(f"Fetching Site CR: {args.site} (namespace: {args.namespace})")
    site_cr = fetch_site_cr(args.site, args.namespace)
    vip_config_toml = generate_vip_config(site_cr, args.target)

    # 3. If --config-only, print and exit
    if args.config_only:
        print(vip_config_toml)
        return

    # Extract Connect URL from site CR for credential operations
    connect_url = _extract_connect_url(site_cr)

    # 4. Handle credentials
    if args.interactive_auth:
        from vip.verify.credentials import mint_interactive_credentials

        if not connect_url:
            print("Error: Connect URL not found in Site CR", file=sys.stderr)
            sys.exit(1)

        print("Minting credentials via interactive auth...")
        mint_interactive_credentials(connect_url, args.site, args.namespace)
    else:
        # Try to ensure Keycloak test user (only if Keycloak is configured)
        keycloak_url = _extract_keycloak_url(site_cr)
        if keycloak_url:
            from vip.verify.credentials import ensure_keycloak_test_user

            admin_secret_name = f"{args.site}-keycloak-initial-admin"
            print(f"Ensuring Keycloak test user exists (admin secret: {admin_secret_name})")
            try:
                ensure_keycloak_test_user(
                    keycloak_url,
                    "posit",  # realm
                    "vip-test-user",
                    admin_secret_name,
                    args.namespace,
                )
            except Exception as e:
                print(f"Warning: Could not create Keycloak test user: {e}", file=sys.stderr)
                print("Continuing without Keycloak credentials...", file=sys.stderr)

    # 5. Run tests
    if args.local:
        _run_local_tests(vip_config_toml, args)
    else:
        _run_k8s_job(vip_config_toml, args)


def _extract_connect_url(site_cr: dict) -> str | None:
    """Extract Connect URL from Site CR."""
    spec = site_cr.get("spec", {})
    connect_spec = spec.get("connect")
    if not connect_spec:
        return None

    domain = spec.get("domain", "")
    prefix = connect_spec.get("domainPrefix", "connect")
    base_domain = connect_spec.get("baseDomain", domain)

    if not base_domain:
        return None

    return f"https://{prefix}.{base_domain}"


def _extract_keycloak_url(site_cr: dict) -> str | None:
    """Extract Keycloak URL from Site CR (if present)."""
    spec = site_cr.get("spec", {})

    # Check if Keycloak is configured (either in connect or workbench auth)
    connect_spec = spec.get("connect", {})
    workbench_spec = spec.get("workbench", {})

    connect_auth = connect_spec.get("auth", {}) if connect_spec else {}
    workbench_auth = workbench_spec.get("auth", {}) if workbench_spec else {}

    # Look for oidc auth type (which typically uses Keycloak)
    if connect_auth.get("type") == "oidc" or workbench_auth.get("type") == "oidc":
        domain = spec.get("domain", "")
        if domain:
            return f"https://key.{domain}"

    return None


def _run_local_tests(vip_config_toml: str, args: argparse.Namespace) -> None:
    """Run VIP tests locally using uv run pytest."""
    # Write config to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write(vip_config_toml)
        config_path = f.name

    try:
        cmd = ["uv", "run", "pytest", f"--vip-config={config_path}"]
        if args.categories:
            cmd.extend(["-m", args.categories])
        cmd.extend(["-v", "--tb=short"])

        print(f"Running tests locally: {' '.join(cmd)}")
        result = subprocess.run(cmd)
        sys.exit(result.returncode)
    finally:
        # Clean up temp file
        Path(config_path).unlink(missing_ok=True)


def _run_k8s_job(vip_config_toml: str, args: argparse.Namespace) -> None:
    """Run VIP tests as a K8s Job."""
    from vip.verify.job import cleanup, create_config_map, create_job, stream_logs, wait_for_job

    suffix = secrets.token_hex(4)
    job_name = f"vip-verify-{suffix}"
    cm_name = f"vip-config-{suffix}"

    try:
        print(f"Creating ConfigMap: {cm_name}")
        create_config_map(cm_name, args.namespace, vip_config_toml)

        print(f"Creating Job: {job_name}")
        create_job(
            job_name,
            args.namespace,
            cm_name,
            image=args.image,
            categories=args.categories,
            interactive_auth=args.interactive_auth,
            timeout_seconds=args.timeout - 60,
        )

        print(f"Streaming logs from Job: {job_name}")
        stream_logs(job_name, args.namespace, timeout=args.timeout)

        print(f"Waiting for Job to complete: {job_name}")
        success = wait_for_job(job_name, args.namespace, timeout=args.timeout)

        if not success:
            print("Verification failed", file=sys.stderr)
            sys.exit(1)
        else:
            print("Verification completed successfully")
    finally:
        print(f"Cleaning up Job and ConfigMap: {job_name}, {cm_name}")
        cleanup(job_name, cm_name, args.namespace)


def run_cleanup(args: argparse.Namespace) -> None:
    """Delete VIP test credentials and resources."""
    from vip.config import load_config
    from vip.verify.credentials import cleanup_credentials
    from vip.verify.site import fetch_site_cr

    config = load_config()

    # Connect to cluster if needed
    if config.cluster.is_configured:
        from vip.cluster.target import validate_cluster_config

        validate_cluster_config(config.cluster)

        if config.cluster.provider == "aws":
            from vip.cluster.aws import get_eks_kubeconfig

            kubeconfig_path = get_eks_kubeconfig(
                config.cluster.name,
                config.cluster.region,
                config.cluster.profile or None,
            )
        elif config.cluster.provider == "azure":
            from vip.cluster.azure import get_aks_kubeconfig

            kubeconfig_path = get_aks_kubeconfig(
                config.cluster.name,
                config.cluster.resource_group,
                config.cluster.subscription_id,
            )

        os.environ["KUBECONFIG"] = str(kubeconfig_path)

    # Fetch Site CR to get Connect URL
    site_cr = fetch_site_cr(args.site, args.namespace)
    connect_url = _extract_connect_url(site_cr)

    print(f"Cleaning up credentials for site: {args.site}")
    cleanup_credentials(args.namespace, connect_url)
    print("Cleanup completed successfully")


def main() -> None:
    """Main entry point for the VIP CLI."""
    parser = argparse.ArgumentParser(
        prog="vip", description="VIP verification and credential tools"
    )
    subparsers = parser.add_subparsers(dest="command")

    # vip auth
    auth_parser = subparsers.add_parser("auth", help="Authentication tools")
    auth_sub = auth_parser.add_subparsers(dest="auth_command")

    # vip auth mint-connect-key
    mint_parser = auth_sub.add_parser(
        "mint-connect-key",
        help="Mint a Connect API key via interactive browser login",
    )
    mint_parser.add_argument("--url", required=True, help="Connect server URL")
    mint_parser.set_defaults(func=mint_connect_key)

    # vip verify
    verify_parser = subparsers.add_parser("verify", help="Verify a Posit Team deployment")
    verify_parser.add_argument(
        "target", help="Target name (informational, used for naming resources)"
    )
    verify_parser.add_argument("--site", default="main", help="Site CR name (default: main)")
    verify_parser.add_argument(
        "--namespace", default="posit-team", help="Kubernetes namespace (default: posit-team)"
    )
    verify_parser.add_argument("--categories", help="Test categories to run (pytest -m marker)")
    verify_parser.add_argument(
        "--local", action="store_true", help="Run tests locally instead of in Kubernetes"
    )
    verify_parser.add_argument(
        "--config-only", action="store_true", help="Generate config only, don't run tests"
    )
    verify_parser.add_argument(
        "--image",
        default="ghcr.io/posit-dev/vip:latest",
        help="VIP container image to use (default: ghcr.io/posit-dev/vip:latest)",
    )
    verify_parser.add_argument(
        "--interactive-auth",
        action="store_true",
        help="Mint credentials via interactive browser login (requires VIP CLI)",
    )
    verify_parser.add_argument(
        "--timeout", type=int, default=900, help="Job timeout in seconds (default: 900)"
    )
    verify_parser.set_defaults(func=run_verify)

    # vip verify cleanup
    verify_sub = verify_parser.add_subparsers(dest="verify_command")
    cleanup_parser = verify_sub.add_parser(
        "cleanup", help="Delete VIP test credentials and resources"
    )
    cleanup_parser.add_argument("target", help="Target name (informational)")
    cleanup_parser.add_argument("--site", default="main", help="Site CR name (default: main)")
    cleanup_parser.add_argument(
        "--namespace", default="posit-team", help="Kubernetes namespace (default: posit-team)"
    )
    cleanup_parser.set_defaults(func=run_cleanup)

    # vip cluster
    cluster_parser = subparsers.add_parser("cluster", help="Cluster connection tools")
    cluster_sub = cluster_parser.add_subparsers(dest="cluster_command")

    # vip cluster connect
    connect_parser = cluster_sub.add_parser("connect", help="Generate kubeconfig for a cluster")
    connect_parser.add_argument("target", help="Target name (informational)")
    connect_parser.add_argument("--provider", help="Cloud provider (aws or azure)")
    connect_parser.add_argument("--cluster-name", help="Cluster name")
    connect_parser.add_argument("--region", help="Cloud region (AWS)")
    connect_parser.add_argument("--resource-group", help="Resource group (Azure)")
    connect_parser.add_argument("--subscription-id", help="Subscription ID (Azure)")
    connect_parser.add_argument("--profile", help="AWS profile name")
    connect_parser.set_defaults(func=connect_to_cluster)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
