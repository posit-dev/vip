"""Tests for vip.config module."""

from __future__ import annotations

import pytest

from vip.config import (
    ClusterConfig,
    ConnectConfig,
    ProductConfig,
    VIPConfig,
    load_config,
)


class TestProductConfig:
    def test_is_configured_when_enabled_and_url_set(self):
        pc = ProductConfig(enabled=True, url="https://example.com")
        assert pc.is_configured is True

    def test_not_configured_when_disabled(self):
        pc = ProductConfig(enabled=False, url="https://example.com")
        assert pc.is_configured is False

    def test_not_configured_when_url_empty(self):
        pc = ProductConfig(enabled=True, url="")
        assert pc.is_configured is False

    def test_not_configured_by_default(self):
        pc = ProductConfig()
        assert pc.is_configured is False


class TestConnectConfig:
    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("VIP_CONNECT_API_KEY", "test-key-123")
        cc = ConnectConfig(url="https://connect.example.com")
        assert cc.api_key == "test-key-123"

    def test_explicit_api_key_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("VIP_CONNECT_API_KEY", "env-key")
        cc = ConnectConfig(url="https://connect.example.com", api_key="explicit-key")
        assert cc.api_key == "explicit-key"


class TestClusterConfig:
    def test_defaults(self):
        cc = ClusterConfig()
        assert cc.provider == ""
        assert cc.name == ""
        assert cc.region == ""
        assert cc.namespace == "posit-team"
        assert cc.site == "main"
        assert cc.profile == ""
        assert cc.subscription_id == ""
        assert cc.resource_group == ""

    def test_is_configured_when_provider_and_name_set(self):
        cc = ClusterConfig(provider="aws", name="test-cluster")
        assert cc.is_configured is True

    def test_not_configured_when_provider_missing(self):
        cc = ClusterConfig(name="test-cluster")
        assert cc.is_configured is False

    def test_not_configured_when_name_missing(self):
        cc = ClusterConfig(provider="aws")
        assert cc.is_configured is False

    def test_not_configured_by_default(self):
        cc = ClusterConfig()
        assert cc.is_configured is False

    def test_env_var_fallback_for_provider(self, monkeypatch):
        monkeypatch.setenv("VIP_CLUSTER_PROVIDER", "azure")
        cc = ClusterConfig()
        assert cc.provider == "azure"

    def test_env_var_fallback_for_name(self, monkeypatch):
        monkeypatch.setenv("VIP_CLUSTER_NAME", "prod-cluster")
        cc = ClusterConfig()
        assert cc.name == "prod-cluster"

    def test_env_var_fallback_for_region(self, monkeypatch):
        monkeypatch.setenv("VIP_CLUSTER_REGION", "us-west-2")
        cc = ClusterConfig()
        assert cc.region == "us-west-2"

    def test_env_var_fallback_for_namespace(self, monkeypatch):
        monkeypatch.setenv("VIP_CLUSTER_NAMESPACE", "custom-namespace")
        cc = ClusterConfig()
        assert cc.namespace == "custom-namespace"

    def test_env_var_fallback_for_aws_profile(self, monkeypatch):
        monkeypatch.setenv("VIP_AWS_PROFILE", "my-profile")
        cc = ClusterConfig()
        assert cc.profile == "my-profile"

    def test_explicit_values_take_precedence(self, monkeypatch):
        monkeypatch.setenv("VIP_CLUSTER_PROVIDER", "aws")
        monkeypatch.setenv("VIP_CLUSTER_NAME", "env-cluster")
        cc = ClusterConfig(provider="azure", name="explicit-cluster")
        assert cc.provider == "azure"
        assert cc.name == "explicit-cluster"


class TestVIPConfig:
    def test_product_config_lookup(self):
        cfg = VIPConfig(
            connect=ConnectConfig(url="https://c.example.com"),
            workbench=ProductConfig(url="https://w.example.com"),
            package_manager=ProductConfig(url="https://p.example.com"),
        )
        assert cfg.product_config("connect").url == "https://c.example.com"
        assert cfg.product_config("workbench").url == "https://w.example.com"
        assert cfg.product_config("package_manager").url == "https://p.example.com"

    def test_product_config_unknown_raises(self):
        cfg = VIPConfig()
        with pytest.raises(ValueError, match="Unknown product"):
            cfg.product_config("bogus")

    def test_defaults(self):
        cfg = VIPConfig()
        assert cfg.deployment_name == "Posit Team"
        assert cfg.extension_dirs == []
        assert cfg.email_enabled is False
        assert cfg.connect.is_configured is False


class TestLoadConfig:
    def test_missing_file_returns_defaults(self, tmp_path):
        cfg = load_config(tmp_path / "nonexistent.toml")
        assert cfg.deployment_name == "Posit Team"
        assert cfg.connect.is_configured is False

    def test_minimal_toml(self, tmp_toml):
        path = tmp_toml(
            """
[general]
deployment_name = "Test Deployment"

[connect]
url = "https://connect.test"
"""
        )
        cfg = load_config(path)
        assert cfg.deployment_name == "Test Deployment"
        assert cfg.connect.url == "https://connect.test"
        assert cfg.connect.is_configured is True
        assert cfg.workbench.is_configured is False

    def test_disabled_product(self, tmp_toml):
        path = tmp_toml(
            """
[connect]
enabled = false
url = "https://connect.test"
"""
        )
        cfg = load_config(path)
        assert cfg.connect.enabled is False
        assert cfg.connect.is_configured is False

    def test_extension_dirs(self, tmp_toml):
        path = tmp_toml(
            """
[general]
extension_dirs = ["/opt/custom-tests", "/srv/more-tests"]
"""
        )
        cfg = load_config(path)
        assert cfg.extension_dirs == ["/opt/custom-tests", "/srv/more-tests"]

    def test_runtimes(self, tmp_toml):
        path = tmp_toml(
            """
[runtimes]
r_versions = ["4.3.2", "4.4.0"]
python_versions = ["3.11.8"]
"""
        )
        cfg = load_config(path)
        assert cfg.runtimes.r_versions == ["4.3.2", "4.4.0"]
        assert cfg.runtimes.python_versions == ["3.11.8"]

    def test_data_sources(self, tmp_toml):
        path = tmp_toml(
            """
[data_sources.mydb]
type = "postgres"
connection_string = "postgresql://localhost/test"
"""
        )
        cfg = load_config(path)
        assert len(cfg.data_sources) == 1
        assert cfg.data_sources[0].name == "mydb"
        assert cfg.data_sources[0].type == "postgres"

    def test_data_source_env_var(self, tmp_toml, monkeypatch):
        monkeypatch.setenv("MY_DB_CONN", "postgresql://secret@db/prod")
        path = tmp_toml(
            """
[data_sources.prod]
type = "postgres"
connection_string_env = "MY_DB_CONN"
"""
        )
        cfg = load_config(path)
        assert cfg.data_sources[0].connection_string == "postgresql://secret@db/prod"

    def test_env_var_config_path(self, tmp_toml, monkeypatch):
        path = tmp_toml(
            """
[general]
deployment_name = "From Env"
"""
        )
        monkeypatch.setenv("VIP_CONFIG", str(path))
        # load_config(None) should pick up VIP_CONFIG.
        cfg = load_config(None)
        assert cfg.deployment_name == "From Env"

    def test_email_and_monitoring_flags(self, tmp_toml):
        path = tmp_toml(
            """
[email]
enabled = true

[monitoring]
enabled = true

[security]
policy_checks_enabled = true
"""
        )
        cfg = load_config(path)
        assert cfg.email_enabled is True
        assert cfg.monitoring_enabled is True
        assert cfg.security_policy_checks_enabled is True

    def test_full_config(self, tmp_toml):
        path = tmp_toml(
            """
[general]
deployment_name = "Full Config"
extension_dirs = ["/ext"]

[connect]
enabled = true
url = "https://connect.example.com"
api_key = "key123"

[workbench]
enabled = true
url = "https://workbench.example.com"

[package_manager]
enabled = false
url = "https://pm.example.com"

[auth]
provider = "ldap"
username = "admin"
password = "secret"

[runtimes]
r_versions = ["4.4.0"]
python_versions = ["3.12.0"]

[email]
enabled = true

[monitoring]
enabled = true

[security]
policy_checks_enabled = true
"""
        )
        cfg = load_config(path)
        assert cfg.deployment_name == "Full Config"
        assert cfg.connect.url == "https://connect.example.com"
        assert cfg.connect.api_key == "key123"
        assert cfg.workbench.is_configured is True
        assert cfg.package_manager.is_configured is False
        assert cfg.auth.provider == "ldap"
        assert cfg.auth.username == "admin"
        assert cfg.runtimes.r_versions == ["4.4.0"]
        assert cfg.email_enabled is True
        assert cfg.monitoring_enabled is True
        assert cfg.security_policy_checks_enabled is True

    def test_cluster_config_from_toml(self, tmp_toml):
        path = tmp_toml(
            """
[cluster]
provider = "aws"
name = "ganso01-staging-20260101"
region = "us-east-1"
namespace = "posit-team"
site = "main"
profile = "ptd-staging"
"""
        )
        cfg = load_config(path)
        assert cfg.cluster.provider == "aws"
        assert cfg.cluster.name == "ganso01-staging-20260101"
        assert cfg.cluster.region == "us-east-1"
        assert cfg.cluster.namespace == "posit-team"
        assert cfg.cluster.site == "main"
        assert cfg.cluster.profile == "ptd-staging"
        assert cfg.cluster.is_configured is True

    def test_cluster_config_azure(self, tmp_toml):
        path = tmp_toml(
            """
[cluster]
provider = "azure"
name = "aks-prod"
region = "eastus"
resource_group = "posit-rg"
subscription_id = "123e4567-e89b-12d3-a456-426614174000"
"""
        )
        cfg = load_config(path)
        assert cfg.cluster.provider == "azure"
        assert cfg.cluster.name == "aks-prod"
        assert cfg.cluster.region == "eastus"
        assert cfg.cluster.resource_group == "posit-rg"
        assert cfg.cluster.subscription_id == "123e4567-e89b-12d3-a456-426614174000"
        assert cfg.cluster.is_configured is True

    def test_missing_cluster_section_uses_defaults(self, tmp_toml):
        path = tmp_toml(
            """
[general]
deployment_name = "No Cluster"
"""
        )
        cfg = load_config(path)
        assert cfg.cluster.is_configured is False
        assert cfg.cluster.namespace == "posit-team"
        assert cfg.cluster.site == "main"
