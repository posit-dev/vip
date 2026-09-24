"""Tests for the ``kubernetes_client`` fixture in vip.fixtures.

Unlike a genuinely unconfigured deployment (``is_configured`` is ``False``,
which still yields ``None``), a *misconfigured* one -- the ``kubernetes`` SDK
missing, an invalid/missing kubeconfig, or any other construction failure --
must fail loudly with a :class:`ConfigError` instead of masquerading as "not
configured" and silently skipping every capacity test. See #609's sibling
fixtures for the ``.__wrapped__`` pattern this uses to call a
``@pytest.fixture``-decorated function directly, bypassing pytest's "fixtures
cannot be called directly" guard.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from vip import fixtures
from vip.config import VIPConfig, WorkbenchConfig, WorkbenchKubernetesConfig
from vip.errors import ConfigError


def _config(**kwargs) -> VIPConfig:
    return VIPConfig(workbench=WorkbenchConfig(kubernetes=WorkbenchKubernetesConfig(**kwargs)))


class TestKubernetesClientFixture:
    def test_returns_none_when_not_configured(self):
        vip_config = _config(enabled=False)

        assert fixtures.kubernetes_client.__wrapped__(vip_config) is None

    def test_raises_config_error_when_sdk_not_installed(self):
        vip_config = _config(enabled=True)

        with (
            patch(
                "vip.fixtures.KubernetesClient",
                side_effect=RuntimeError("The 'kubernetes' package is required"),
            ),
            pytest.raises(ConfigError, match=r"kubernetes.*package.*required"),
        ):
            fixtures.kubernetes_client.__wrapped__(vip_config)

    def test_raises_config_error_on_invalid_kubeconfig(self):
        vip_config = _config(enabled=True, namespace="custom-ns")

        class _FakeConfigError(Exception):
            pass

        with (
            patch(
                "vip.fixtures.KubernetesClient",
                side_effect=_FakeConfigError("invalid kube-config"),
            ),
            pytest.raises(ConfigError, match="custom-ns"),
        ):
            fixtures.kubernetes_client.__wrapped__(vip_config)

    def test_raises_config_error_on_unreadable_kubeconfig(self):
        """Not every kubeconfig failure is ``kubernetes.config.ConfigException``
        -- an unreadable or malformed file surfaces as ``OSError``/``yaml.YAMLError``
        from deeper in the SDK's loader, and must convert just the same.
        """
        vip_config = _config(enabled=True, namespace="custom-ns")

        with (
            patch(
                "vip.fixtures.KubernetesClient",
                side_effect=PermissionError("kubeconfig not readable"),
            ),
            pytest.raises(ConfigError, match="custom-ns"),
        ):
            fixtures.kubernetes_client.__wrapped__(vip_config)

    def test_returns_client_when_construction_succeeds(self):
        vip_config = _config(enabled=True, namespace="posit-team")
        sentinel = object()

        with patch("vip.fixtures.KubernetesClient", return_value=sentinel) as mock_client:
            result = fixtures.kubernetes_client.__wrapped__(vip_config)

        mock_client.assert_called_once_with(namespace="posit-team")
        assert result is sentinel
