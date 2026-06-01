"""Tests for WorkbenchKubernetesConfig in vip.config."""

from __future__ import annotations

import pytest

from vip.config import (
    VIPConfig,
    WorkbenchConfig,
    WorkbenchKubernetesConfig,
    load_config,
)


class TestWorkbenchKubernetesConfig:
    def test_defaults(self):
        cfg = WorkbenchKubernetesConfig()
        assert cfg.enabled is False
        assert cfg.namespace == "posit-team"
        assert cfg.node_pool_profiles == {}
        assert cfg.max_sessions is None
        assert cfg.profile_cpu_limit == {}
        assert cfg.profile_memory_limit_gib == {}

    def test_is_configured_false_by_default(self):
        cfg = WorkbenchKubernetesConfig()
        assert cfg.is_configured is False

    def test_is_configured_when_enabled(self):
        cfg = WorkbenchKubernetesConfig(enabled=True)
        assert cfg.is_configured is True

    def test_from_dict_empty(self):
        cfg = WorkbenchKubernetesConfig.from_dict({})
        assert cfg.enabled is False
        assert cfg.namespace == "posit-team"

    def test_from_dict_enabled(self):
        cfg = WorkbenchKubernetesConfig.from_dict({"enabled": True, "namespace": "wb"})
        assert cfg.enabled is True
        assert cfg.namespace == "wb"

    def test_from_dict_node_pool_profiles(self):
        cfg = WorkbenchKubernetesConfig.from_dict(
            {
                "enabled": True,
                "node_pool_profiles": {"cpu-pool": "Small", "gpu-pool": "GPU Large"},
            }
        )
        assert cfg.node_pool_profiles == {"cpu-pool": "Small", "gpu-pool": "GPU Large"}

    def test_from_dict_max_sessions(self):
        cfg = WorkbenchKubernetesConfig.from_dict({"max_sessions": 10})
        assert cfg.max_sessions == 10

    def test_from_dict_resource_limits(self):
        cfg = WorkbenchKubernetesConfig.from_dict(
            {
                "profile_cpu_limit": {"Small": 1.0, "Large": 4.0},
                "profile_memory_limit_gib": {"Small": 2.0, "Large": 8.0},
            }
        )
        assert cfg.profile_cpu_limit == {"Small": 1.0, "Large": 4.0}
        assert cfg.profile_memory_limit_gib == {"Small": 2.0, "Large": 8.0}


class TestWorkbenchConfigWithKubernetes:
    def test_kubernetes_defaults_to_not_configured(self):
        cfg = WorkbenchConfig()
        assert cfg.kubernetes.is_configured is False

    def test_from_dict_without_kubernetes_block(self):
        cfg = WorkbenchConfig.from_dict({"url": "https://wb.example.com"})
        assert cfg.kubernetes.enabled is False

    def test_from_dict_with_kubernetes_block(self):
        cfg = WorkbenchConfig.from_dict(
            {
                "url": "https://wb.example.com",
                "kubernetes": {"enabled": True, "namespace": "custom-ns"},
            }
        )
        assert cfg.kubernetes.enabled is True
        assert cfg.kubernetes.namespace == "custom-ns"

    def test_repr_includes_kubernetes(self):
        cfg = WorkbenchConfig(url="https://wb.example.com")
        r = repr(cfg)
        assert "kubernetes=" in r


class TestLoadConfigWithKubernetes:
    def test_load_config_without_k8s_section(self, tmp_path):
        toml = tmp_path / "vip.toml"
        toml.write_text('[workbench]\nurl = "https://wb.example.com"\n')
        cfg = load_config(toml)
        assert cfg.workbench.kubernetes.enabled is False
        assert cfg.workbench.kubernetes.is_configured is False

    def test_load_config_with_k8s_section(self, tmp_path):
        toml = tmp_path / "vip.toml"
        toml.write_text(
            '[workbench]\nurl = "https://wb.example.com"\n\n'
            "[workbench.kubernetes]\n"
            "enabled = true\n"
            'namespace = "posit-team"\n'
            "max_sessions = 5\n"
        )
        cfg = load_config(toml)
        assert cfg.workbench.kubernetes.enabled is True
        assert cfg.workbench.kubernetes.namespace == "posit-team"
        assert cfg.workbench.kubernetes.max_sessions == 5

    def test_load_config_k8s_with_profile_mappings(self, tmp_path):
        toml = tmp_path / "vip.toml"
        toml.write_text(
            '[workbench]\nurl = "https://wb.example.com"\n\n'
            "[workbench.kubernetes]\n"
            "enabled = true\n"
            "[workbench.kubernetes.node_pool_profiles]\n"
            '"cpu-pool" = "Small"\n'
            "[workbench.kubernetes.profile_cpu_limit]\n"
            '"Small" = 1.0\n'
        )
        cfg = load_config(toml)
        assert cfg.workbench.kubernetes.node_pool_profiles == {"cpu-pool": "Small"}
        assert cfg.workbench.kubernetes.profile_cpu_limit == {"Small": 1.0}
