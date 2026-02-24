"""Root conftest - shared fixtures for all VIP tests."""

from __future__ import annotations

import pytest

from vip.clients.connect import ConnectClient
from vip.clients.packagemanager import PackageManagerClient
from vip.clients.workbench import WorkbenchClient
from vip.config import VIPConfig
from vip.plugin import _auth_state_key, _vip_config_key

# ---------------------------------------------------------------------------
# Configuration fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def vip_config(request: pytest.FixtureRequest) -> VIPConfig:
    """The loaded VIP configuration for this test run."""
    return request.config.stash[_vip_config_key]


# ---------------------------------------------------------------------------
# Product client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def connect_client(vip_config: VIPConfig) -> ConnectClient | None:
    if not vip_config.connect.is_configured:
        return None
    client = ConnectClient(vip_config.connect.url, vip_config.connect.api_key)
    yield client
    client.close()


@pytest.fixture(scope="session")
def connect_url(vip_config: VIPConfig) -> str:
    return vip_config.connect.url


@pytest.fixture(scope="session")
def workbench_client(vip_config: VIPConfig) -> WorkbenchClient | None:
    if not vip_config.workbench.is_configured:
        return None
    client = WorkbenchClient(vip_config.workbench.url)
    yield client
    client.close()


@pytest.fixture(scope="session")
def workbench_url(vip_config: VIPConfig) -> str:
    return vip_config.workbench.url


@pytest.fixture(scope="session")
def pm_client(vip_config: VIPConfig) -> PackageManagerClient | None:
    if not vip_config.package_manager.is_configured:
        return None
    client = PackageManagerClient(vip_config.package_manager.url)
    yield client
    client.close()


@pytest.fixture(scope="session")
def pm_url(vip_config: VIPConfig) -> str:
    return vip_config.package_manager.url


# ---------------------------------------------------------------------------
# Auth fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def interactive_auth(request: pytest.FixtureRequest) -> bool:
    """Whether interactive auth was used for this session."""
    return request.config.stash.get(_auth_state_key, None) is not None


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, request: pytest.FixtureRequest):
    """Inject interactive auth storage state into all browser contexts."""
    state_path = request.config.stash.get(_auth_state_key, None)
    if state_path:
        browser_context_args["storage_state"] = state_path
    return browser_context_args


@pytest.fixture(scope="session")
def test_username(vip_config: VIPConfig) -> str:
    return vip_config.auth.username


@pytest.fixture(scope="session")
def test_password(vip_config: VIPConfig) -> str:
    return vip_config.auth.password


@pytest.fixture(scope="session")
def auth_provider(vip_config: VIPConfig) -> str:
    return vip_config.auth.provider


# ---------------------------------------------------------------------------
# Runtime fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def expected_r_versions(vip_config: VIPConfig) -> list[str]:
    return vip_config.runtimes.r_versions


@pytest.fixture(scope="session")
def expected_python_versions(vip_config: VIPConfig) -> list[str]:
    return vip_config.runtimes.python_versions


# ---------------------------------------------------------------------------
# Data source fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def data_sources(vip_config: VIPConfig):
    return vip_config.data_sources


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def email_enabled(vip_config: VIPConfig) -> bool:
    return vip_config.email_enabled


@pytest.fixture(scope="session")
def monitoring_enabled(vip_config: VIPConfig) -> bool:
    return vip_config.monitoring_enabled
