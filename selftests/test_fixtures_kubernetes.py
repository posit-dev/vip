"""Tests for the ``kubernetes_client`` fixture in vip.fixtures.

Unlike a genuinely unconfigured deployment (``is_configured`` is ``False``,
which still yields ``None``), a *misconfigured* one -- the ``kubernetes`` SDK
missing, or an invalid/missing kubeconfig -- must fail loudly with a
:class:`ConfigError` instead of masquerading as "not configured" and silently
skipping every capacity test. See #609's sibling fixtures for the
``.__wrapped__`` pattern this uses to call a ``@pytest.fixture``-decorated
function directly, bypassing pytest's "fixtures cannot be called directly"
guard.
"""

from __future__ import annotations

import sys
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

        fake_kubernetes_config = type(sys)("kubernetes.config")
        fake_kubernetes_config.ConfigException = _FakeConfigError

        with (
            patch.dict(sys.modules, {"kubernetes.config": fake_kubernetes_config}),
            patch(
                "vip.fixtures.KubernetesClient",
                side_effect=_FakeConfigError("invalid kube-config"),
            ),
            pytest.raises(ConfigError, match="custom-ns"),
        ):
            fixtures.kubernetes_client.__wrapped__(vip_config)

    def test_unexpected_exception_propagates_unconverted(self):
        """A bug in construction is not a config problem -- it must not be
        misreported as one.
        """
        vip_config = _config(enabled=True)

        class _FakeConfigError(Exception):
            pass

        fake_kubernetes_config = type(sys)("kubernetes.config")
        fake_kubernetes_config.ConfigException = _FakeConfigError

        with (
            patch.dict(sys.modules, {"kubernetes.config": fake_kubernetes_config}),
            patch("vip.fixtures.KubernetesClient", side_effect=TypeError("unexpected bug")),
            pytest.raises(TypeError, match="unexpected bug"),
        ):
            fixtures.kubernetes_client.__wrapped__(vip_config)

    def test_returns_client_when_construction_succeeds(self):
        vip_config = _config(enabled=True, namespace="posit-team")
        sentinel = object()

        with patch("vip.fixtures.KubernetesClient", return_value=sentinel) as mock_client:
            result = fixtures.kubernetes_client.__wrapped__(vip_config)

        mock_client.assert_called_once_with(namespace="posit-team")
        assert result is sentinel
