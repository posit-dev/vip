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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vip.config import Mode


def _connect_cluster(cluster_config) -> Path:
    """Generate kubeconfig and set KUBECONFIG env var. Returns the path."""
    from vip.cluster.target import validate_cluster_config

    validate_cluster_config(cluster_config)

    if cluster_config.provider == "aws":
        from vip.cluster.aws import get_eks_kubeconfig

        kubeconfig_path = get_eks_kubeconfig(
            cluster_config.name,
            cluster_config.region,
            cluster_config.profile or None,
            cluster_config.role_arn or None,
        )
    elif cluster_config.provider == "azure":
        from vip.cluster.azure import get_aks_kubeconfig

        kubeconfig_path = get_aks_kubeconfig(
            cluster_config.name,
            cluster_config.resource_group,
            cluster_config.subscription_id,
        )
    else:
        raise ValueError(f"Unknown provider: {cluster_config.provider!r}")

    os.environ["KUBECONFIG"] = str(kubeconfig_path)
    print(f"Connected to cluster: {cluster_config.name}", file=sys.stderr)
    return kubeconfig_path


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

    kubeconfig_path = _connect_cluster(config.cluster)
    print(str(kubeconfig_path))


def _resolve_mode(args: argparse.Namespace) -> Mode:
    """Convert boolean CLI flags to a Mode enum value."""
    from vip.config import Mode

    if args.config_only:
        return Mode.config_only
    if args.local:
        return Mode.local
    return Mode.k8s_job


def _phase_generate_config(args: argparse.Namespace) -> tuple[str, dict]:
    """Fetch Site CR and return (vip_config_toml, site_cr) tuple."""
    from vip.verify.site import fetch_site_cr, generate_vip_config

    print(f"Fetching Site CR: {args.site} (namespace: {args.namespace})")
    site_cr = fetch_site_cr(args.site, args.namespace)
    return generate_vip_config(site_cr, args.target), site_cr


def _phase_provision_credentials(site_cr: dict, args: argparse.Namespace) -> None:
    """Provision test credentials in the K8s cluster."""
    if args.interactive_auth:
        from vip.verify.credentials import mint_interactive_credentials

        connect_url = _extract_connect_url(site_cr)
        if not connect_url:
            print("Error: Connect URL not found in Site CR", file=sys.stderr)
            sys.exit(1)
        print("Minting credentials via interactive auth...")
        mint_interactive_credentials(connect_url, args.site, args.namespace)
    else:
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


def _phase_run_tests(vip_config_toml: str, mode: Mode, args: argparse.Namespace) -> None:
    """Run tests locally or as a K8s Job depending on mode."""
    from vip.config import Mode

    if mode == Mode.local:
        _run_local_tests(vip_config_toml, args)
    else:
        _run_k8s_job(vip_config_toml, args)


def run_verify(args: argparse.Namespace) -> None:
    """Main verification flow."""
    from vip.config import Mode, load_config

    config = load_config()
    mode = _resolve_mode(args)
    config.validate_for_mode(mode)

    # Connect to cluster for modes that need it
    if config.cluster.is_configured:
        _connect_cluster(config.cluster)

    vip_config_toml, site_cr = _phase_generate_config(args)

    if mode == Mode.config_only:
        print(vip_config_toml)
        return

    _phase_provision_credentials(site_cr, args)
    _phase_run_tests(vip_config_toml, mode, args)


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
        _connect_cluster(config.cluster)

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
    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify a Posit Team deployment",
        description=(
            "Verify a Posit Team deployment by fetching its Site CR, generating "
            "a vip.toml, provisioning test credentials, and running the test suite.\n\n"
            "Execution modes:\n"
            "  (default)           Submit a Kubernetes Job and stream its logs\n"
            "  --local             Run pytest on this machine\n"
            "  --config-only       Generate vip.toml only, print and exit\n\n"
            "Credential modes:\n"
            "  (default)           Create a Keycloak test user (requires Keycloak OIDC)\n"
            "  --interactive-auth  Mint credentials via browser login"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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

    # Map command names to their parsers for context-appropriate help
    subcommand_parsers = {
        "auth": auth_parser,
        "verify": verify_parser,
        "cluster": cluster_parser,
    }

    args = parser.parse_args()
    if not hasattr(args, "func"):
        # Show help for the subcommand the user navigated to, not top-level
        sub = subcommand_parsers.get(args.command)
        if sub:
            sub.print_help()
        else:
            parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
