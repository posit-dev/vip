"""Tests for vip.config module."""

from __future__ import annotations

import pytest

from vip.config import (
    AuthConfig,
    ClusterConfig,
    ConnectConfig,
    Mode,
    PerformanceConfig,
    ProductConfig,
    VIPConfig,
    load_config,
)


class TestAuthConfig:
    def test_idp_defaults_to_empty(self):
        ac = AuthConfig()
        assert ac.idp == ""

    def test_idp_from_constructor(self):
        ac = AuthConfig(idp="keycloak")
        assert ac.idp == "keycloak"

    def test_from_dict_with_idp(self):
        ac = AuthConfig.from_dict({"provider": "oidc", "idp": "okta"})
        assert ac.idp == "okta"

    def test_from_dict_without_idp(self):
        ac = AuthConfig.from_dict({"provider": "password"})
        assert ac.idp == ""


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

    def test_url_normalized_when_scheme_missing(self):
        cc = ConnectConfig(url="connect.example.com")
        assert cc.url == "http://connect.example.com"

    def test_url_host_only_no_trailing_slash(self):
        cc = ConnectConfig(url="https://connect.example.com")
        assert cc.url == "https://connect.example.com"

    def test_url_host_only_trailing_slash_stripped(self):
        cc = ConnectConfig(url="https://connect.example.com/")
        assert cc.url == "https://connect.example.com"

    def test_url_subpath_gets_trailing_slash(self):
        cc = ConnectConfig(url="https://host.example.com/connect")
        assert cc.url == "https://host.example.com/connect/"

    def test_default_deploy_timeout(self):
        cc = ConnectConfig(url="https://connect.example.com")
        assert cc.deploy_timeout == 600

    def test_explicit_deploy_timeout(self):
        cc = ConnectConfig(url="https://connect.example.com", deploy_timeout=1200)
        assert cc.deploy_timeout == 1200


class TestPerformanceConfig:
    def test_defaults(self):
        pc = PerformanceConfig()
        assert pc.page_load_timeout == 10.0
        assert pc.download_timeout == 30.0
        assert pc.p95_response_time == 5.0
        assert pc.concurrent_requests == 10
        assert pc.disk_usage_max_pct == 90.0
        assert pc.memory_available_min_pct == 10.0

    def test_from_dict_partial(self):
        pc = PerformanceConfig.from_dict({"page_load_timeout": 15.0})
        assert pc.page_load_timeout == 15.0
        assert pc.download_timeout == 30.0  # default preserved

    def test_from_dict_empty(self):
        pc = PerformanceConfig.from_dict({})
        assert pc.page_load_timeout == 10.0

    def test_load_defaults(self):
        pc = PerformanceConfig()
        assert pc.load_user_counts == [10, 100, 1_000, 10_000]
        assert pc.load_max_connections == 200
        assert pc.load_success_rate_threshold == 0.95
        assert pc.load_test_tool == "auto"
        assert pc.load_test_duration == 30
        assert pc.load_test_spawn_rate == 10

    def test_load_from_dict(self):
        pc = PerformanceConfig.from_dict(
            {
                "load_user_counts": [5, 50],
                "load_max_connections": 100,
                "load_success_rate_threshold": 0.90,
                "load_test_tool": "async",
                "load_test_duration": 60,
                "load_test_spawn_rate": 20,
            }
        )
        assert pc.load_user_counts == [5, 50]
        assert pc.load_max_connections == 100
        assert pc.load_success_rate_threshold == 0.90
        assert pc.load_test_tool == "async"
        assert pc.load_test_duration == 60
        assert pc.load_test_spawn_rate == 20


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

    def test_performance_section(self, tmp_toml):
        path = tmp_toml(
            """
[performance]
page_load_timeout = 20.0
p95_response_time = 3.0
concurrent_requests = 5
"""
        )
        cfg = load_config(path)
        assert cfg.performance.page_load_timeout == 20.0
        assert cfg.performance.p95_response_time == 3.0
        assert cfg.performance.concurrent_requests == 5
        assert cfg.performance.download_timeout == 30.0  # default

    def test_performance_defaults_when_section_missing(self, tmp_toml):
        path = tmp_toml('[general]\ndeployment_name = "Test"\n')
        cfg = load_config(path)
        assert cfg.performance.page_load_timeout == 10.0

    def test_deploy_timeout_from_toml(self, tmp_toml):
        path = tmp_toml(
            """
[connect]
url = "https://connect.example.com"
deploy_timeout = 1200
"""
        )
        cfg = load_config(path)
        assert cfg.connect.deploy_timeout == 1200

    def test_deploy_timeout_defaults_when_missing(self, tmp_toml):
        path = tmp_toml(
            """
[connect]
url = "https://connect.example.com"
"""
        )
        cfg = load_config(path)
        assert cfg.connect.deploy_timeout == 600

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


class TestMode:
    def test_enum_values(self):
        assert Mode.local.value == "local"
        assert Mode.k8s_job.value == "k8s_job"
        assert Mode.config_only.value == "config_only"

    def test_str_comparison(self):
        assert Mode.local == "local"


class TestVIPConfigValidateForMode:
    def test_local_mode_no_cluster_required(self):
        cfg = VIPConfig()  # no cluster configured
        cfg.validate_for_mode(Mode.local)  # must not raise

    def test_k8s_job_requires_cluster(self):
        cfg = VIPConfig()
        with pytest.raises(ValueError, match="cluster configuration"):
            cfg.validate_for_mode(Mode.k8s_job)

    def test_k8s_job_passes_with_cluster(self):
        cfg = VIPConfig(cluster=ClusterConfig(provider="aws", name="my-cluster"))
        cfg.validate_for_mode(Mode.k8s_job)  # must not raise

    def test_config_only_requires_cluster(self):
        cfg = VIPConfig()
        with pytest.raises(ValueError, match="cluster configuration"):
            cfg.validate_for_mode(Mode.config_only)
