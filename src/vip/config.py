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


@dataclass
class ProductConfig:
    """Configuration for a single Posit product."""

    enabled: bool = True
    url: str = ""
    version: str | None = None

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.url)


@dataclass
class ConnectConfig(ProductConfig):
    """Connect-specific configuration."""

    api_key: str = ""

    def __post_init__(self) -> None:
        if not self.api_key:
            self.api_key = os.environ.get("VIP_CONNECT_API_KEY", "")


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
    workbench: ProductConfig = field(default_factory=ProductConfig)
    package_manager: ProductConfig = field(default_factory=ProductConfig)

    auth: AuthConfig = field(default_factory=AuthConfig)
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
        ),
        workbench=ProductConfig(
            enabled=workbench_raw.get("enabled", True),
            url=workbench_raw.get("url", ""),
            version=workbench_raw.get("version"),
        ),
        package_manager=ProductConfig(
            enabled=pm_raw.get("enabled", True),
            url=pm_raw.get("url", ""),
            version=pm_raw.get("version"),
        ),
        auth=AuthConfig(
            provider=auth_raw.get("provider", "password"),
            username=auth_raw.get("username", ""),
            password=auth_raw.get("password", ""),
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
