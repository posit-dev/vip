"""VIP's core pytest fixtures and shared BDD step definitions.

These used to live in ``src/vip_tests/conftest.py``. pytest scopes
``conftest.py`` fixtures by directory ancestry, so a test collected from
outside ``src/vip_tests`` -- exactly what an extension directory loaded via
``--vip-extensions`` (or ``extension_dirs`` in vip.toml) is -- could never see
them: requesting ``vip_config`` failed with ``fixture 'vip_config' not
found`` (issue #609), even though ``pytest_sessionstart`` in ``vip.plugin``
makes such a directory collectible.

This module is not a plugin by itself and is never imported at ``vip.plugin``
module scope. ``vip.plugin.pytest_configure`` registers it with pluggy under
the explicit name ``"vip-fixtures"`` (see ``register`` below), which makes
every fixture and step below visible in *any* pytest session where ``vip`` is
installed -- independent of directory ancestry, and identically on xdist
workers (``pytest_configure`` runs once per worker process, same as the
controller).

Registering a dedicated module under its own name -- rather than importing
``vip_tests.conftest`` directly via ``pluginmanager.import_plugin`` -- avoids
a real failure mode: when ``vip_tests`` is *also* collected as a directory
(exactly what ``vip verify`` does), pytest auto-registers that same
``conftest.py`` module under its path-derived name, and registering the
identical module object under a second, explicit name raises ``ValueError:
Plugin already registered under a different name``. ``vip/fixtures.py`` is
never a ``conftest.py`` and is never auto-discovered by pytest, so no such
collision is possible here.

Just as important: these fixtures live in exactly *one* place. Session-scoped
fixtures like ``connect_client`` must resolve to a single ``FixtureDef`` for
an entire run, or a run that collects both ``src/vip_tests`` and an extension
directory together (again, what ``vip verify`` does) would build two
independent ``ConnectClient`` instances -- and, worse, two independent browser
auth sessions -- one for each scope. ``src/vip_tests/conftest.py`` therefore
does not redefine or re-export any of these names; it only keeps the
directory-scoped warning filter that must *not* travel with this module (see
that file's docstring).

One deliberate exception: the three Connect content-cleanup fixtures
(``_connect_created_guids``, ``_connect_content_cleanup``,
``_connect_end_of_run_sweep``) stay in ``src/vip_tests/conftest.py`` and are
*not* part of this module. Two of them are ``autouse=True``, which -- unlike
an ordinary fixture a test has to request -- runs for every test collected in
a session, unconditionally. Registering them here would make every pytest
run anywhere ``vip`` is installed pay for Connect-content bookkeeping it never
asked for, and it is not merely a cost: a project with its own unrelated
``vip.toml`` that happens to configure ``[connect]`` without an API key (for
reasons that have nothing to do with VIP's product tests) would have every one
of its tests fail in setup, because ``_connect_content_cleanup`` requests
``connect_client``, which calls ``require_connect_api_key`` and fails loudly
when Connect is configured but unauthenticated. This was caught empirically:
``selftests/test_plugin.py::TestPluginIntegration::
test_bdd_given_configured_product_not_deselected`` configures Connect with no
API key to exercise deselection logic, and broke exactly this way when the
cleanup fixtures were briefly moved here during development. Extension
directories therefore do not get automatic Connect-content cleanup -- a real,
known gap, not an oversight. An extension author who creates Connect content
today has to clean it up the same way any pytest-bdd test outside VIP would:
with its own fixture, or by calling ``connect_client.cleanup_content(...)``
directly.
"""

from __future__ import annotations

import pytest
from pytest_bdd import given

from vip.auth import resolve_url_scheme
from vip.client_auth import build_client_auth
from vip.clients.connect import ConnectClient
from vip.clients.kubernetes import KubernetesClient
from vip.clients.packagemanager import PackageManagerClient
from vip.clients.workbench import WorkbenchClient
from vip.config import PerformanceConfig, VIPConfig

# ---------------------------------------------------------------------------
# Configuration fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def vip_config(request: pytest.FixtureRequest) -> VIPConfig:
    """The loaded VIP configuration for this test run."""
    from vip.plugin import _vip_config_key

    return request.config.stash[_vip_config_key]


@pytest.fixture(scope="session")
def vip_verbose(request: pytest.FixtureRequest) -> bool:
    """Whether --vip-verbose was passed on the command line."""
    return request.config.getoption("--vip-verbose", default=False)


# ---------------------------------------------------------------------------
# Product client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def connect_client(request: pytest.FixtureRequest, vip_config: VIPConfig) -> ConnectClient | None:
    from vip.plugin import _auth_session_key, require_connect_api_key

    if not vip_config.connect.is_configured:
        # Yield (not return) None: this is a generator fixture, and the root
        # autouse Connect-cleanup fixtures request it on every test — including
        # PM-only and Workbench-only runs where Connect is unconfigured.  A bare
        # ``return`` here would raise "connect_client did not yield a value".
        yield None
        return
    # --interactive-auth/--headless-auth already resolve this in vip.plugin
    # before any browser touches the URL; resolve_url_scheme no-ops (and
    # doesn't touch the network) if that already happened -- this call is
    # what covers --api-auth/--no-auth, where no auth flow runs and this
    # fixture is the first thing to talk to the server. resolve_url_scheme
    # mutates vip_config.connect.url in place, so every fixture that reads it
    # afterward -- whichever one a test asks for first -- converges on the
    # same value, and its own cache means asking from more than one fixture
    # for the same product only probes the network once.
    url = resolve_url_scheme(
        vip_config.connect,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
        proxy=vip_config.proxy,
    )
    # A registered client-auth provider (e.g. Snowflake JWT) authenticates the
    # request itself, so a Connect API key is not required in that case.
    auth = build_client_auth(vip_config, "connect", url)
    if auth is None:
        require_connect_api_key(vip_config)
    # When an interactive/headless auth session exists, load the gateway cookies
    # from the saved Playwright storage state and inject them into the httpx
    # client.  An OIDC forward-auth proxy (e.g. Okta) that fronts Connect will
    # 307-redirect /__api__/... requests to the IdP unless its session cookie
    # rides alongside the Connect API key.
    session = request.config.stash.get(_auth_session_key, None)
    cookies = session.load_cookies() if session is not None else None
    client = ConnectClient(
        url,
        api_key=vip_config.connect.api_key,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
        auth=auth,
        cookies=cookies,
        proxy=vip_config.proxy,
    )
    yield client
    client.close()


@pytest.fixture(scope="session")
def connect_url(vip_config: VIPConfig) -> str:
    return resolve_url_scheme(
        vip_config.connect,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
        proxy=vip_config.proxy,
    )


@pytest.fixture(scope="session")
def workbench_client(
    request: pytest.FixtureRequest, vip_config: VIPConfig
) -> WorkbenchClient | None:
    from vip.plugin import _auth_session_key

    if not vip_config.workbench.is_configured:
        # Yield (not return) None so this generator fixture always yields a value —
        # autouse cleanup fixtures that request workbench_client would get
        # "fixture did not yield a value" from a bare return.
        yield None
        return
    url = resolve_url_scheme(
        vip_config.workbench,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
        proxy=vip_config.proxy,
    )
    auth = build_client_auth(vip_config, "workbench", url)
    # Same gateway-cookie injection as connect_client: the identical OIDC proxy
    # that fronts Connect also fronts Workbench on these deployments.
    session = request.config.stash.get(_auth_session_key, None)
    cookies = session.load_cookies() if session is not None else None
    client = WorkbenchClient(
        url,
        api_key=vip_config.workbench.api_key,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
        auth=auth,
        cookies=cookies,
        proxy=vip_config.proxy,
    )
    yield client
    client.close()


@pytest.fixture(scope="session")
def workbench_url(vip_config: VIPConfig) -> str:
    return resolve_url_scheme(
        vip_config.workbench,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
        proxy=vip_config.proxy,
    )


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
    url = resolve_url_scheme(
        vip_config.package_manager,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
        proxy=vip_config.proxy,
    )
    auth = build_client_auth(vip_config, "package_manager", url)
    client = PackageManagerClient(
        url,
        token=vip_config.package_manager.token,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
        auth=auth,
        proxy=vip_config.proxy,
    )
    yield client
    client.close()


@pytest.fixture(scope="session")
def pm_url(vip_config: VIPConfig) -> str:
    return resolve_url_scheme(
        vip_config.package_manager,
        insecure=vip_config.insecure,
        ca_bundle=vip_config.ca_bundle,
        proxy=vip_config.proxy,
    )


# ---------------------------------------------------------------------------
# Auth fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def interactive_auth(request: pytest.FixtureRequest) -> bool:
    """Whether any pre-test auth flow established a browser session.

    Returns True for both ``--interactive-auth`` and ``--headless-auth``; use
    the ``auth_mode`` fixture to distinguish which mode is active.
    """
    from vip.plugin import _auth_session_key

    session = request.config.stash.get(_auth_session_key, None)
    return session is not None


@pytest.fixture(scope="session")
def auth_mode(request: pytest.FixtureRequest) -> str:
    """The active auth mode: ``"interactive"``, ``"headless"``, or ``"none"``."""
    from vip.plugin import _auth_mode_key

    return request.config.stash.get(_auth_mode_key, "none")


@pytest.fixture(scope="session")
def workbench_auth_error(request: pytest.FixtureRequest) -> str | None:
    """Reason Workbench auth did not complete during pre-test sign-in, if any.

    Returns ``None`` when Workbench was authenticated successfully or
    when no pre-test auth ran.  Tests that depend on Workbench storage
    state can read this to produce an informative skip message instead
    of a generic "session not shared" guess.
    """
    from vip.plugin import _auth_session_key

    session = request.config.stash.get(_auth_session_key, None)
    if session is None:
        return None
    return session.workbench_auth_error


def _ui_browser_proxy(vip_config: VIPConfig) -> dict[str, str] | None:
    """The Playwright ``proxy`` dict for in-suite UI tests, or ``None``.

    Routes the UI-test browsers through the same proxy as the API clients and
    the auth-mint browser, so a ``[proxy]``/``--proxy`` config (or the ambient
    proxy env) applies uniformly to Playwright too -- Chromium's own env-proxy
    detection is platform-dependent, so we set it explicitly.

    Resolved against the URL these browsers actually drive, because Playwright
    takes a single proxy server per context and the http and https proxies can
    differ: picking the https one for an http:// Workbench would put the browser
    on a different gateway than every httpx call to the same host. Workbench is
    preferred as the target since it owns the bulk of the UI tests; NO_PROXY
    hosts are still handled per-request through the ``bypass`` list.

    The target goes through ``resolve_url_scheme`` first. This fixture is
    session-scoped and depends only on ``vip_config``, so nothing orders it after
    the client fixtures that resolve those URLs -- reading a scheme-less
    ``--workbench-url`` raw would pick the proxy for the *inferred* ``https://``
    and then leave the browser on that gateway after the URL downgraded to
    ``http://``, which is the split this helper exists to prevent. The call is
    memoized and idempotent, so doing it here costs nothing.

    ``None`` (no proxy applies) leaves the browser args untouched, so the default
    stays exactly as pytest-playwright had it.
    """
    from vip.proxy import build_proxy_map, playwright_proxy

    for pc in (vip_config.workbench, vip_config.connect, vip_config.package_manager):
        if not pc.url:
            continue
        target = resolve_url_scheme(
            pc,
            insecure=vip_config.insecure,
            ca_bundle=vip_config.ca_bundle,
            proxy=vip_config.proxy,
        )
        return playwright_proxy(build_proxy_map(vip_config.proxy), target or None)
    return playwright_proxy(build_proxy_map(vip_config.proxy))


def _ui_browser_launch_args(vip_config: VIPConfig) -> list[str]:
    """Extra Chromium switches for the in-suite UI browsers.

    ``--no-proxy-server`` when the user explicitly disabled proxying: a context
    with no ``proxy`` key leaves Chromium free to pick up the ambient proxy
    environment or system settings, which would proxy the browser while every
    httpx call goes direct. See :func:`vip.proxy.chromium_launch_args`.
    """
    from vip.proxy import chromium_launch_args

    return chromium_launch_args(vip_config.proxy)


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args, vip_config: VIPConfig):
    """Apply the resolved proxy to the UI-test browsers at launch.

    Overrides the pytest-playwright fixture of the same name; the parameter name
    *must* match to receive the base fixture value.

    Both the proxy and ``--no-proxy-server`` are set here so the in-suite
    browsers and the auth browsers in ``vip.auth`` configure the same thing the
    same way -- ``_launch_chromium`` passes both at launch, and having one entry
    point do it per-context invited the two to drift. ``--no-proxy-server`` has
    to be launch-level regardless (it is a browser switch, not a context
    option), and the two are mutually exclusive: ``chromium_launch_args``
    returns nothing whenever a proxy is configured.

    This overrides a *plugin* fixture (pytest-playwright's), not a conftest
    one -- see the module docstring for why these fixtures live only here.
    Registering ``vip-fixtures`` in ``pytest_configure`` (after pytest-playwright
    has already registered via its own entry point) is what makes this
    override win; ``selftests/test_extension_fixtures.py`` and
    ``selftests/test_plugin.py`` assert VIP's version is the one in effect,
    not just that the fixture resolves.
    """
    extra = _ui_browser_launch_args(vip_config)
    if extra:
        browser_type_launch_args["args"] = [
            *browser_type_launch_args.get("args", []),
            *extra,
        ]
    pw_proxy = _ui_browser_proxy(vip_config)
    if pw_proxy is not None:
        browser_type_launch_args["proxy"] = pw_proxy
    return browser_type_launch_args


@pytest.fixture(scope="session")
def browser_context_args(
    browser_context_args, request: pytest.FixtureRequest, vip_config: VIPConfig
):
    """Inject interactive auth storage state and TLS config into all browser contexts.

    Overrides the pytest-playwright fixture of the same name.  The parameter
    name *must* match to receive the base fixture value.  See
    ``browser_type_launch_args`` above for why this override still applies
    after moving out of ``conftest.py``.
    """
    from vip.plugin import _auth_session_key

    session = request.config.stash.get(_auth_session_key, None)
    if session is not None:
        browser_context_args["storage_state"] = str(session.storage_state_path)
    if vip_config.insecure:
        browser_context_args["ignore_https_errors"] = True
    # The proxy is applied at launch (see browser_type_launch_args), not here.
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


def register(config: pytest.Config) -> None:
    """Register this module as a pytest plugin, if not already registered.

    Called from ``vip.plugin.pytest_configure`` -- see the module docstring
    for why a dedicated name (rather than re-registering ``vip_tests.conftest``
    under a second name) is required, and why registering here rather than at
    import time gives VIP's ``browser_type_launch_args``/``browser_context_args``
    overrides priority over pytest-playwright's own fixtures of the same name.
    """
    name = "vip-fixtures"
    if config.pluginmanager.has_plugin(name):
        return
    import vip.fixtures as _fixtures_module

    config.pluginmanager.register(_fixtures_module, name=name)
