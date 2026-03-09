"""Load and validate VIP configuration."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def _normalize_url(url: str) -> str:
    """Ensure a URL has a scheme (default to http if missing)."""
    if not url:
        return url
    if not url.startswith(("http://", "https://")):
        return f"http://{url}"
    return url


@dataclass
class ProductConfig:
    """Configuration for a single Posit product."""

    enabled: bool = True
    url: str = ""
    version: str | None = None

    def __post_init__(self) -> None:
        self.url = _normalize_url(self.url)

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.url)


@dataclass
class ConnectConfig(ProductConfig):
    """Connect-specific configuration."""

    api_key: str = ""
    deploy_timeout: int = 600

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.api_key:
            self.api_key = os.environ.get("VIP_CONNECT_API_KEY", "")


@dataclass
class WorkbenchConfig(ProductConfig):
    """Workbench-specific configuration."""

    api_key: str = ""

    def __post_init__(self) -> None:
        if not self.api_key:
            self.api_key = os.environ.get("VIP_WORKBENCH_API_KEY", "")


@dataclass
class PackageManagerConfig(ProductConfig):
    """Package Manager-specific configuration."""

    token: str = ""

    def __post_init__(self) -> None:
        if not self.token:
            self.token = os.environ.get("VIP_PM_TOKEN", "")


@dataclass
class AuthConfig:
    """Authentication configuration."""

    provider: str = "password"
    username: str = ""
    password: str = ""

    def __post_init__(self) -> None:
        if not self.username:
            self.username = os.environ.get("VIP_TEST_USERNAME", "")
        if not self.password:
            self.password = os.environ.get("VIP_TEST_PASSWORD", "")


@dataclass
class ClusterConfig:
    """Kubernetes cluster access configuration."""

    provider: str = ""  # "aws" or "azure"
    name: str = ""  # Cluster name (e.g., "ganso01-staging-20260101")
    region: str = ""  # Cloud region
    namespace: str = "posit-team"  # K8s namespace for Posit products
    site: str = "main"  # Site CR name

    # AWS-specific
    profile: str = ""  # AWS profile name
    role_arn: str = ""  # IAM role ARN for cross-account access

    # Azure-specific
    subscription_id: str = ""  # Azure subscription ID
    resource_group: str = ""  # Azure resource group

    @property
    def is_configured(self) -> bool:
        return bool(self.provider and self.name)

    def __post_init__(self) -> None:
        if not self.provider:
            self.provider = os.environ.get("VIP_CLUSTER_PROVIDER", "")
        if not self.name:
            self.name = os.environ.get("VIP_CLUSTER_NAME", "")
        if not self.region:
            self.region = os.environ.get("VIP_CLUSTER_REGION", "")
        if not self.namespace or self.namespace == "posit-team":
            env_ns = os.environ.get("VIP_CLUSTER_NAMESPACE", "")
            if env_ns:
                self.namespace = env_ns
        if not self.profile:
            self.profile = os.environ.get("VIP_AWS_PROFILE", "")
        if not self.role_arn:
            self.role_arn = os.environ.get("VIP_AWS_ROLE_ARN", "")


@dataclass
class DataSourceEntry:
    """A single external data source to verify."""

    name: str = ""
    type: str = ""
    connection_string: str = ""


@dataclass
class RuntimesConfig:
    """Expected R and Python runtime versions."""

    r_versions: list[str] = field(default_factory=list)
    python_versions: list[str] = field(default_factory=list)


@dataclass
class VIPConfig:
    """Top-level VIP configuration."""

    deployment_name: str = "Posit Team"
    extension_dirs: list[str] = field(default_factory=list)

    connect: ConnectConfig = field(default_factory=ConnectConfig)
    workbench: WorkbenchConfig = field(default_factory=WorkbenchConfig)
    package_manager: PackageManagerConfig = field(default_factory=PackageManagerConfig)

    auth: AuthConfig = field(default_factory=AuthConfig)
    cluster: ClusterConfig = field(default_factory=ClusterConfig)
    runtimes: RuntimesConfig = field(default_factory=RuntimesConfig)
    data_sources: list[DataSourceEntry] = field(default_factory=list)

    email_enabled: bool = False
    monitoring_enabled: bool = False
    security_policy_checks_enabled: bool = False

    def product_config(self, product: str) -> ProductConfig:
        """Look up a product configuration by name."""
        mapping: dict[str, ProductConfig] = {
            "connect": self.connect,
            "workbench": self.workbench,
            "package_manager": self.package_manager,
        }
        if product not in mapping:
            raise ValueError(f"Unknown product: {product!r}")
        return mapping[product]


def load_config(path: str | Path | None = None) -> VIPConfig:
    """Load VIP configuration from a TOML file.

    Resolution order when *path* is ``None``:
    1. ``VIP_CONFIG`` environment variable
    2. ``vip.toml`` in the current working directory
    """
    if path is None:
        env = os.environ.get("VIP_CONFIG")
        if env:
            path = Path(env)
        else:
            path = Path("vip.toml")

    path = Path(path)
    if not path.exists():
        # Return default config when no file is present - tests will be
        # skipped for unconfigured products.
        return VIPConfig()

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    general = raw.get("general", {})
    connect_raw = raw.get("connect", {})
    workbench_raw = raw.get("workbench", {})
    pm_raw = raw.get("package_manager", {})
    auth_raw = raw.get("auth", {})
    cluster_raw = raw.get("cluster", {})
    runtimes_raw = raw.get("runtimes", {})
    email_raw = raw.get("email", {})
    monitoring_raw = raw.get("monitoring", {})
    security_raw = raw.get("security", {})
    data_sources_raw = raw.get("data_sources", {})

    data_sources: list[DataSourceEntry] = []
    for name, ds in data_sources_raw.items():
        conn_str = ds.get("connection_string", "")
        env_key = ds.get("connection_string_env")
        if env_key:
            conn_str = os.environ.get(env_key, conn_str)
        data_sources.append(
            DataSourceEntry(name=name, type=ds.get("type", ""), connection_string=conn_str)
        )

    return VIPConfig(
        deployment_name=general.get("deployment_name", "Posit Team"),
        extension_dirs=general.get("extension_dirs", []),
        connect=ConnectConfig(
            enabled=connect_raw.get("enabled", True),
            url=connect_raw.get("url", ""),
            version=connect_raw.get("version"),
            api_key=connect_raw.get("api_key", ""),
            deploy_timeout=connect_raw.get("deploy_timeout", 600),
        ),
        workbench=WorkbenchConfig(
            enabled=workbench_raw.get("enabled", True),
            url=workbench_raw.get("url", ""),
            version=workbench_raw.get("version"),
            api_key=workbench_raw.get("api_key", ""),
        ),
        package_manager=PackageManagerConfig(
            enabled=pm_raw.get("enabled", True),
            url=pm_raw.get("url", ""),
            version=pm_raw.get("version"),
            token=pm_raw.get("token", ""),
        ),
        auth=AuthConfig(
            provider=auth_raw.get("provider", "password"),
            username=auth_raw.get("username", ""),
            password=auth_raw.get("password", ""),
        ),
        cluster=ClusterConfig(
            provider=cluster_raw.get("provider", ""),
            name=cluster_raw.get("name", ""),
            region=cluster_raw.get("region", ""),
            namespace=cluster_raw.get("namespace", "posit-team"),
            site=cluster_raw.get("site", "main"),
            profile=cluster_raw.get("profile", ""),
            role_arn=cluster_raw.get("role_arn", ""),
            subscription_id=cluster_raw.get("subscription_id", ""),
            resource_group=cluster_raw.get("resource_group", ""),
        ),
        runtimes=RuntimesConfig(
            r_versions=runtimes_raw.get("r_versions", []),
            python_versions=runtimes_raw.get("python_versions", []),
        ),
        data_sources=data_sources,
        email_enabled=email_raw.get("enabled", False),
        monitoring_enabled=monitoring_raw.get("enabled", False),
        security_policy_checks_enabled=security_raw.get("policy_checks_enabled", False),
    )
