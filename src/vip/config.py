"""Load and validate VIP configuration."""

from __future__ import annotations

import enum
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


class Mode(str, enum.Enum):
    """Execution mode for a VIP verification run.

    local       -- run pytest directly on the caller's machine
    k8s_job     -- submit a Kubernetes Job and stream its logs
    config_only -- generate vip.toml from the PTD Site CR and print it; no tests run
    """

    local = "local"
    k8s_job = "k8s_job"
    config_only = "config_only"


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

    @classmethod
    def from_dict(cls, raw: dict) -> ConnectConfig:
        return cls(
            enabled=raw.get("enabled", True),
            url=raw.get("url", ""),
            version=raw.get("version"),
            api_key=raw.get("api_key", ""),
            deploy_timeout=raw.get("deploy_timeout", 600),
        )


@dataclass
class WorkbenchConfig(ProductConfig):
    """Workbench-specific configuration."""

    api_key: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.api_key:
            self.api_key = os.environ.get("VIP_WORKBENCH_API_KEY", "")

    @classmethod
    def from_dict(cls, raw: dict) -> WorkbenchConfig:
        return cls(
            enabled=raw.get("enabled", True),
            url=raw.get("url", ""),
            version=raw.get("version"),
            api_key=raw.get("api_key", ""),
        )


@dataclass
class PackageManagerConfig(ProductConfig):
    """Package Manager-specific configuration."""

    token: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.token:
            self.token = os.environ.get("VIP_PM_TOKEN", "")

    @classmethod
    def from_dict(cls, raw: dict) -> PackageManagerConfig:
        return cls(
            enabled=raw.get("enabled", True),
            url=raw.get("url", ""),
            version=raw.get("version"),
            token=raw.get("token", ""),
        )


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

    @classmethod
    def from_dict(cls, raw: dict) -> AuthConfig:
        return cls(
            provider=raw.get("provider", "password"),
            username=raw.get("username", ""),
            password=raw.get("password", ""),
        )


@dataclass
class ClusterConfig:
    """Kubernetes cluster access configuration."""

    provider: str = ""  # "aws" or "azure"
    name: str = ""  # Cluster name (e.g., "ganso01-staging-20260101")
    region: str = ""  # Cloud region
    namespace: str = ""  # K8s namespace for Posit products
    site: str = "main"  # PTD Site CR name (posit-dev/team-operator)

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
        if not self.namespace:
            env_ns = os.environ.get("VIP_CLUSTER_NAMESPACE", "")
            self.namespace = env_ns if env_ns else "posit-team"
        if not self.profile:
            self.profile = os.environ.get("VIP_AWS_PROFILE", "")
        if not self.role_arn:
            self.role_arn = os.environ.get("VIP_AWS_ROLE_ARN", "")

    @classmethod
    def from_dict(cls, raw: dict) -> ClusterConfig:
        return cls(
            provider=raw.get("provider", ""),
            name=raw.get("name", ""),
            region=raw.get("region", ""),
            namespace=raw.get("namespace", ""),
            site=raw.get("site", "main"),
            profile=raw.get("profile", ""),
            role_arn=raw.get("role_arn", ""),
            subscription_id=raw.get("subscription_id", ""),
            resource_group=raw.get("resource_group", ""),
        )


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

    def validate_for_mode(self, mode: Mode) -> None:
        """Raise ValueError if required fields are missing for *mode*.

        Call this after loading config from file and after CLI overrides
        have been applied, before executing any I/O.

        Fields required by mode:
          local:       none beyond product URLs (config.py defaults are fine)
          k8s_job:     cluster.is_configured (provider + name)
          config_only: cluster.is_configured (need to reach the API server)
        """
        if mode in (Mode.k8s_job, Mode.config_only):
            if not self.cluster.is_configured:
                raise ValueError(
                    f"mode={mode.value!r} requires cluster configuration "
                    "(set [cluster] provider and name in vip.toml or via env vars "
                    "VIP_CLUSTER_PROVIDER and VIP_CLUSTER_NAME)"
                )

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
    data_sources_raw = raw.get("data_sources", {})
    email_raw = raw.get("email", {})
    monitoring_raw = raw.get("monitoring", {})
    security_raw = raw.get("security", {})
    runtimes_raw = raw.get("runtimes", {})

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
        connect=ConnectConfig.from_dict(raw.get("connect", {})),
        workbench=WorkbenchConfig.from_dict(raw.get("workbench", {})),
        package_manager=PackageManagerConfig.from_dict(raw.get("package_manager", {})),
        auth=AuthConfig.from_dict(raw.get("auth", {})),
        cluster=ClusterConfig.from_dict(raw.get("cluster", {})),
        runtimes=RuntimesConfig(
            r_versions=runtimes_raw.get("r_versions", []),
            python_versions=runtimes_raw.get("python_versions", []),
        ),
        data_sources=data_sources,
        email_enabled=email_raw.get("enabled", False),
        monitoring_enabled=monitoring_raw.get("enabled", False),
        security_policy_checks_enabled=security_raw.get("policy_checks_enabled", False),
    )
