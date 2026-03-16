"""PTD Site CR parsing and VIP config generation.

The PTD Site CR is a custom resource managed by the Posit Team Deployer
(team-operator): https://github.com/posit-dev/team-operator
"""

from __future__ import annotations

import json
import subprocess
from typing import Any


def fetch_site_cr(site_name: str, namespace: str = "posit-team") -> dict[str, Any]:
    """Fetch a PTD Site CR from the cluster via kubectl.

    The PTD Site CR is managed by posit-dev/team-operator.

    Args:
        site_name: Name of the PTD Site custom resource
        namespace: Kubernetes namespace (default: "posit-team")

    Returns:
        Parsed PTD Site CR as a dictionary

    Raises:
        subprocess.CalledProcessError: If kubectl command fails
        json.JSONDecodeError: If kubectl output is not valid JSON
    """
    cmd = ["kubectl", "get", "site", site_name, "-n", namespace, "-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def generate_vip_config(site_cr: dict[str, Any], deployment_name: str) -> str:
    """Generate vip.toml content from a PTD Site CR.

    Args:
        site_cr: Parsed PTD Site custom resource dictionary
        deployment_name: Human-readable deployment name for the config

    Returns:
        vip.toml content as a string

    Raises:
        ValueError: If site_cr is invalid or missing required fields
    """
    if not site_cr:
        raise ValueError("site_cr cannot be empty")

    spec = site_cr.get("spec", {})
    domain = spec.get("domain", "")
    connect_spec = spec.get("connect")
    workbench_spec = spec.get("workbench")
    pm_spec = spec.get("packageManager")

    # Verify domain is present when any product needs it
    needs_domain = (
        (connect_spec is not None and connect_spec.get("baseDomain", "") == "")
        or (workbench_spec is not None and workbench_spec.get("baseDomain", "") == "")
        or (pm_spec is not None and pm_spec.get("baseDomain", "") == "")
    )
    if domain == "" and needs_domain:
        raise ValueError(
            "site domain is required when products are configured without a per-product baseDomain"
        )

    # Determine auth provider (Connect > Workbench > default "oidc")
    # PackageManager is intentionally excluded from auth detection
    auth_provider = "oidc"
    connect_has_auth = False
    if connect_spec is not None:
        connect_auth = connect_spec.get("auth")
        if connect_auth and connect_auth.get("type", "") != "":
            auth_provider = connect_auth["type"]
            connect_has_auth = True

    # Only check Workbench if Connect didn't provide auth
    if not connect_has_auth and workbench_spec is not None:
        workbench_auth = workbench_spec.get("auth")
        if workbench_auth and workbench_auth.get("type", "") != "":
            auth_provider = workbench_auth["type"]

    # Build product configs
    connect_enabled = connect_spec is not None
    connect_url = ""
    if connect_enabled:
        connect_url = _build_product_url(connect_spec, "connect", domain)

    workbench_enabled = workbench_spec is not None
    workbench_url = ""
    if workbench_enabled:
        workbench_url = _build_product_url(workbench_spec, "workbench", domain)

    pm_enabled = pm_spec is not None
    pm_url = ""
    if pm_enabled:
        pm_url = _build_product_url(pm_spec, "packagemanager", domain)

    # Format TOML (manually, since we support Python 3.10)
    lines = [
        "[general]",
        f'deployment_name = "{deployment_name}"',
        "",
        "[connect]",
        f"enabled = {_bool_str(connect_enabled)}",
    ]
    if connect_url:
        lines.append(f'url = "{connect_url}"')

    lines.extend(
        [
            "",
            "[workbench]",
            f"enabled = {_bool_str(workbench_enabled)}",
        ]
    )
    if workbench_url:
        lines.append(f'url = "{workbench_url}"')

    lines.extend(
        [
            "",
            "[package_manager]",
            f"enabled = {_bool_str(pm_enabled)}",
        ]
    )
    if pm_url:
        lines.append(f'url = "{pm_url}"')

    lines.extend(
        [
            "",
            "[auth]",
            f'provider = "{auth_provider}"',
            "",
            "[email]",
            "enabled = false",
            "",
            "[monitoring]",
            "enabled = false",
            "",
            "[security]",
            "policy_checks_enabled = false",
        ]
    )

    return "\n".join(lines) + "\n"


def _build_product_url(
    product_spec: dict[str, Any] | None, default_prefix: str, base_domain: str
) -> str:
    """Construct the product URL from the product spec.

    The prefix (DomainPrefix or defaultPrefix) is always prepended to the domain, so
    ProductSpec.BaseDomain must be a bare parent domain (e.g. "example.com"), not a
    fully-qualified hostname that already includes the product subdomain.

    Args:
        product_spec: Product specification dictionary (or None)
        default_prefix: Default domain prefix (e.g. "connect", "workbench", "packagemanager")
        base_domain: Site-level base domain (fallback if product has no baseDomain)

    Returns:
        Product URL as "https://{prefix}.{domain}", or empty string if no domain available
    """
    if product_spec is None:
        if base_domain == "":
            return ""
        return f"https://{default_prefix}.{base_domain}"

    prefix = product_spec.get("domainPrefix", default_prefix)
    if prefix == "":
        prefix = default_prefix

    domain = product_spec.get("baseDomain", base_domain)
    if domain == "":
        domain = base_domain

    if domain == "":
        return ""

    return f"https://{prefix}.{domain}"


def _bool_str(value: bool) -> str:
    """Format a boolean for TOML output."""
    return "true" if value else "false"


def _extract_connect_url(site_cr: dict[str, Any]) -> str | None:
    """Extract Connect URL from a PTD Site CR."""
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


def _extract_keycloak_url(site_cr: dict[str, Any]) -> str | None:
    """Extract Keycloak URL from a PTD Site CR (if present)."""
    spec = site_cr.get("spec", {})

    connect_spec = spec.get("connect", {})
    workbench_spec = spec.get("workbench", {})

    connect_auth = connect_spec.get("auth", {}) if connect_spec else {}
    workbench_auth = workbench_spec.get("auth", {}) if workbench_spec else {}

    if connect_auth.get("type") == "oidc" or workbench_auth.get("type") == "oidc":
        domain = spec.get("domain", "")
        if domain:
            return f"https://key.{domain}"

    return None
