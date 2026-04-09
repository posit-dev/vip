"""Load and validate VIP configuration."""

from __future__ import annotations

import enum
import os
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse, urlunparse

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
    """Ensure a URL has a scheme and, for sub-path URLs, a trailing slash.

    Scheme normalization: if no scheme is present, ``http://`` is added.

    Trailing-slash normalization: a trailing slash is added **only** when the
    URL has a non-root path component (e.g. ``/pwb`` or ``/connect``).  Without
    it, nginx redirects ``https://host/pwb`` → ``http://host/pwb/`` (note: HTTP,
    not HTTPS), which Playwright cannot follow in a headless HTTPS context.

    Host-only URLs (e.g. ``https://connect.example.com``) are left without a
    trailing slash so that callers can safely build API URLs via
    ``f"{url}/__api__/..."`` without introducing double slashes.
    """
    if not url:
        return url
    if not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    parsed = urlparse(url)
    path = parsed.path
    if path and path != "/":
        # Sub-path URL: ensure trailing slash to prevent the nginx HTTP redirect.
        if not path.endswith("/"):
            path = path + "/"
    else:
        # Host-only URL: normalise to no trailing slash so f"{url}/..." is safe.
        path = ""
    return urlunparse(parsed._replace(path=path))


def _as_str_list(value: object, field_name: str) -> list[str]:
    """Coerce *value* to a list of strings, or raise on bad input."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    raise ValueError(f"{field_name} must be a list of strings, got {type(value).__name__}")


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
    deploy_timeout: int = 1200

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
            deploy_timeout=raw.get("deploy_timeout", 1200),
        )


@dataclass
class WorkbenchExtensionsConfig:
    """Additional IDE extensions the admin expects to be installed.

    These are merged with the built-in Posit Workbench integration
    extension that is always validated.
    """

    vscode: list[str] = field(default_factory=list)
    positron: list[str] = field(default_factory=list)
    jupyterlab: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> WorkbenchExtensionsConfig:
        return cls(
            vscode=_as_str_list(raw.get("vscode", []), "workbench.extensions.vscode"),
            positron=_as_str_list(raw.get("positron", []), "workbench.extensions.positron"),
            jupyterlab=_as_str_list(raw.get("jupyterlab", []), "workbench.extensions.jupyterlab"),
        )


@dataclass
class WorkbenchConfig(ProductConfig):
    """Workbench-specific configuration."""

    api_key: str = ""
    # Resource profiles to test for session capacity.  None = auto-detect
    # from the UI dropdown; explicit list = test only these profiles.
    session_profiles: list[str] | None = None
    session_count: int = 3  # sessions per profile in capacity tests
    extensions: WorkbenchExtensionsConfig = field(default_factory=WorkbenchExtensionsConfig)

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
            session_profiles=raw.get("session_profiles"),
            session_count=raw.get("session_count", 3),
            extensions=WorkbenchExtensionsConfig.from_dict(raw.get("extensions", {})),
        )


@dataclass
class PackageManagerConfig(ProductConfig):
    """Package Manager-specific configuration."""

    token: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.token:
            self.token = os.environ.get(
                "VIP_PACKAGE_MANAGER_TOKEN", os.environ.get("VIP_PM_TOKEN", "")
            )

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
    idp: str = ""

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
            idp=raw.get("idp", ""),
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
class PerformanceConfig:
    """Thresholds for performance tests."""

    page_load_timeout: float = 10.0  # seconds
    download_timeout: float = 30.0
    p95_response_time: float = 5.0
    avg_response_time: float = 5.0
    concurrent_requests: int = 10
    disk_usage_max_pct: float = 90.0
    memory_available_min_pct: float = 10.0

    # Load test configuration
    load_user_counts: list[int] = field(default_factory=lambda: [10, 100, 1_000, 10_000])
    load_max_connections: int = 200
    load_success_rate_threshold: float = 0.95
    load_test_tool: str = "auto"  # "auto" | "async" | "locust" | "threadpool"
    load_test_duration: int = 30  # seconds (locust only)
    load_test_spawn_rate: int = 10  # users/sec (locust only)

    @classmethod
    def from_dict(cls, raw: dict) -> PerformanceConfig:
        return cls(
            page_load_timeout=raw.get("page_load_timeout", 10.0),
            download_timeout=raw.get("download_timeout", 30.0),
            p95_response_time=raw.get("p95_response_time", 5.0),
            avg_response_time=raw.get("avg_response_time", 5.0),
            concurrent_requests=raw.get("concurrent_requests", 10),
            disk_usage_max_pct=raw.get("disk_usage_max_pct", 90.0),
            memory_available_min_pct=raw.get("memory_available_min_pct", 10.0),
            load_user_counts=raw.get("load_user_counts", [10, 100, 1_000, 10_000]),
            load_max_connections=raw.get("load_max_connections", 200),
            load_success_rate_threshold=raw.get("load_success_rate_threshold", 0.95),
            load_test_tool=raw.get("load_test_tool", "auto"),
            load_test_duration=raw.get("load_test_duration", 30),
            load_test_spawn_rate=raw.get("load_test_spawn_rate", 10),
        )


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
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)
    data_sources: list[DataSourceEntry] = field(default_factory=list)

    email_enabled: bool = False
    monitoring_enabled: bool = False
    security_policy_checks_enabled: bool = False

    insecure: bool = False
    ca_bundle: Path | None = None

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


def _resolve_ca_bundle(raw: str | None) -> Path | None:
    """Return a validated ``Path`` for the CA bundle, or ``None``.

    Raises ``ValueError`` if the path is specified but does not point to an
    existing file, so misconfigured deployments fail fast with a clear message
    rather than producing an opaque SSL error on the first HTTP request.
    """
    if not raw:
        return None
    p = Path(raw)
    if not p.is_file():
        raise ValueError(f"[tls] ca_bundle path does not exist or is not a file: {p}")
    return p


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
        warnings.warn(f"Config file not found: {path}", stacklevel=2)
        return VIPConfig()

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    general = raw.get("general", {})
    data_sources_raw = raw.get("data_sources", {})
    email_raw = raw.get("email", {})
    monitoring_raw = raw.get("monitoring", {})
    security_raw = raw.get("security", {})
    runtimes_raw = raw.get("runtimes", {})
    performance_raw = raw.get("performance", {})
    tls_raw = raw.get("tls", {})

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
        performance=PerformanceConfig.from_dict(performance_raw),
        data_sources=data_sources,
        email_enabled=email_raw.get("enabled", False),
        monitoring_enabled=monitoring_raw.get("enabled", False),
        security_policy_checks_enabled=security_raw.get("policy_checks_enabled", False),
        insecure=tls_raw.get("insecure", False),
        ca_bundle=_resolve_ca_bundle(tls_raw.get("ca_bundle")),
    )
