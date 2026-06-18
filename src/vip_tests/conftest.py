"""Root conftest - shared fixtures and step definitions for all VIP tests."""

from __future__ import annotations

import pytest
from pytest_bdd import given

from vip.client_auth import build_client_auth
from vip.clients.connect import ConnectClient
from vip.clients.kubernetes import KubernetesClient
from vip.clients.packagemanager import PackageManagerClient
from vip.clients.workbench import WorkbenchClient
from vip.config import PerformanceConfig, VIPConfig
from vip.plugin import (
    _auth_mode_key,
    _auth_session_key,
    _vip_config_key,
    require_connect_api_key,
)

# pytest-bdd step definitions with target_fixture return values intentionally;
# pytest 9.x warns about non-None returns from test functions. Scoped to
# vip_tests only so selftests still catch accidental returns.
pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestReturnNotNoneWarning")

# ---------------------------------------------------------------------------
# Configuration fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def vip_config(request: pytest.FixtureRequest) -> VIPConfig:
    """The loaded VIP configuration for this test run."""
    return request.config.stash[_vip_config_key]


@pytest.fixture(scope="session")
def vip_verbose(request: pytest.FixtureRequest) -> bool:
    """Whether --vip-verbose was passed on the command line."""
    return request.config.getoption("--vip-verbose", default=False)


# ---------------------------------------------------------------------------
# Product client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def connect_client(vip_config: VIPConfig) -> ConnectClient | None:
    if not vip_config.connect.is_configured:
        # Yield (not return) None: this is a generator fixture, and the root
        # autouse Connect-cleanup fixtures request it on every test — including
        # PM-only and Workbench-only runs where Connect is unconfigured.  A bare
        # ``return`` here would raise "connect_client did not yield a value".
        yield None
        return
    # A registered client-auth provider (e.g. Snowflake JWT) authenticates the
    # request itself, so a Connect API key is not required in that case.
    auth = build_client_auth(vip_config, "connect", vip_config.connect.url)
    if auth is None:
        require_connect_api_key(vip_config)
    client = ConnectClient(
        vip_config.connect.url,
        api_key=vip_config.connect.api_key,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
        auth=auth,
    )
    yield client
    client.close()


@pytest.fixture(scope="session")
def connect_url(vip_config: VIPConfig) -> str:
    return vip_config.connect.url


@pytest.fixture(scope="session")
def workbench_client(vip_config: VIPConfig) -> WorkbenchClient | None:
    if not vip_config.workbench.is_configured:
        return None
    auth = build_client_auth(vip_config, "workbench", vip_config.workbench.url)
    client = WorkbenchClient(
        vip_config.workbench.url,
        api_key=vip_config.workbench.api_key,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
        auth=auth,
    )
    yield client
    client.close()


@pytest.fixture(scope="session")
def workbench_url(vip_config: VIPConfig) -> str:
    return vip_config.workbench.url


@pytest.fixture(scope="session")
def kubernetes_client(vip_config: VIPConfig) -> KubernetesClient | None:
    """Kubernetes client for capacity tests; ``None`` when K8s is not configured."""
    k8s_cfg = vip_config.workbench.kubernetes
    if not k8s_cfg.is_configured:
        return None
    try:
        return KubernetesClient(namespace=k8s_cfg.namespace)
    except Exception:
        return None


@pytest.fixture(scope="session")
def pm_client(vip_config: VIPConfig) -> PackageManagerClient | None:
    if not vip_config.package_manager.is_configured:
        return None
    auth = build_client_auth(vip_config, "package_manager", vip_config.package_manager.url)
    client = PackageManagerClient(
        vip_config.package_manager.url,
        token=vip_config.package_manager.token,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
        auth=auth,
    )
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
    """Whether any pre-test auth flow established a browser session.

    Returns True for both ``--interactive-auth`` and ``--headless-auth``; use
    the ``auth_mode`` fixture to distinguish which mode is active.
    """
    session = request.config.stash.get(_auth_session_key, None)
    return session is not None


@pytest.fixture(scope="session")
def auth_mode(request: pytest.FixtureRequest) -> str:
    """The active auth mode: ``"interactive"``, ``"headless"``, or ``"none"``."""
    return request.config.stash.get(_auth_mode_key, "none")


@pytest.fixture(scope="session")
def workbench_auth_error(request: pytest.FixtureRequest) -> str | None:
    """Reason Workbench auth did not complete during pre-test sign-in, if any.

    Returns ``None`` when Workbench was authenticated successfully or
    when no pre-test auth ran.  Tests that depend on Workbench storage
    state can read this to produce an informative skip message instead
    of a generic "session not shared" guess.
    """
    session = request.config.stash.get(_auth_session_key, None)
    if session is None:
        return None
    return session.workbench_auth_error


@pytest.fixture(scope="session")
def browser_context_args(
    browser_context_args, request: pytest.FixtureRequest, vip_config: VIPConfig
):
    """Inject interactive auth storage state and TLS config into all browser contexts.

    Overrides the pytest-playwright fixture of the same name.  The parameter
    name *must* match to receive the base fixture value.
    """
    session = request.config.stash.get(_auth_session_key, None)
    if session is not None:
        browser_context_args["storage_state"] = str(session.storage_state_path)
    if vip_config.insecure:
        browser_context_args["ignore_https_errors"] = True
    if vip_config.ca_bundle is not None:
        import os

        _prev = os.environ.get("NODE_EXTRA_CA_CERTS")
        os.environ["NODE_EXTRA_CA_CERTS"] = str(vip_config.ca_bundle)

        def _restore_node_ca() -> None:
            if _prev is None:
                os.environ.pop("NODE_EXTRA_CA_CERTS", None)
            else:
                os.environ["NODE_EXTRA_CA_CERTS"] = _prev

        request.addfinalizer(_restore_node_ca)
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
# Performance fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def performance_config(vip_config: VIPConfig) -> PerformanceConfig:
    return vip_config.performance


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
def chronicle_enabled(vip_config: VIPConfig) -> bool:
    return vip_config.chronicle_enabled


# ---------------------------------------------------------------------------
# Connect content cleanup — promoted from connect/conftest.py so that any
# package (workbench, cross_product, …) that creates Connect content can
# register GUIDs into the shared tracking list.  The fixtures guard against
# ``connect_client is None`` so they are safe to activate in workbench-only
# runs where Connect is not configured.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _connect_created_guids():
    """Append-only record of content GUIDs created this run (tag-independent)."""
    return []


@pytest.fixture(autouse=True)
def _connect_content_cleanup(connect_client, _connect_created_guids):
    """Delete content created during this test, on pass or fail."""
    start = len(_connect_created_guids)
    yield
    if connect_client is None:
        return
    created = _connect_created_guids[start:]
    if created:
        connect_client.cleanup_content(created)


@pytest.fixture(scope="session", autouse=True)
def _connect_end_of_run_sweep(connect_client, _connect_created_guids):
    """End-of-run safety net: delete tracked GUIDs, then tag-based cross-run sweep."""
    yield
    if connect_client is None:
        return
    if _connect_created_guids:
        connect_client.cleanup_content(_connect_created_guids)
    connect_client.cleanup_vip_content()


# ---------------------------------------------------------------------------
# Shared BDD steps — product configuration guards
# ---------------------------------------------------------------------------


@given("Connect is configured in vip.toml")
def connect_configured(vip_config):
    if not vip_config.connect.is_configured:
        pytest.skip("Connect is not configured")


@given("Workbench is configured in vip.toml")
def workbench_configured(vip_config):
    if not vip_config.workbench.is_configured:
        pytest.skip("Workbench is not configured")


@given("Package Manager is configured in vip.toml")
def package_manager_configured(vip_config):
    if not vip_config.package_manager.is_configured:
        pytest.skip("Package Manager is not configured")
