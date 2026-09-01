"""Selftest fixtures.

These tests verify the VIP framework itself and can run without any Posit
products.  They are separate from the ``tests/`` directory which contains
the actual verification suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Enable the pytester fixture for plugin integration tests.
pytest_plugins = ["pytester"]

_PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


@pytest.fixture(autouse=True)
def _restore_auth_entrypoints():
    """Undo in-process ``pytester`` runs that rebind ``vip.auth``'s entrypoints.

    Several plugin tests write a conftest that stubs authentication with
    ``vip.auth.start_interactive_auth = _fake_session``.  Those runs execute
    ``runpytest_inprocess`` -- the same interpreter, the same ``vip.auth``
    module object -- so the assignment outlives the inner session and every
    later selftest that calls the real function silently gets the stub back
    (an ``InteractiveAuthSession`` with a ``/dev/null`` storage state), passing
    or failing for reasons that have nothing to do with what it asserts.

    Snapshot and restore around every test so the leak cannot cross a test
    boundary.  Cheap, and it fixes the whole class of leak rather than the two
    conftests that happen to cause it today.
    """
    import vip.auth as _auth

    saved = {
        name: getattr(_auth, name) for name in ("start_interactive_auth", "start_headless_auth")
    }
    yield
    for name, func in saved.items():
        setattr(_auth, name, func)


@pytest.fixture(autouse=True)
def _no_ambient_proxy(monkeypatch):
    """Clear proxy environment variables for every selftest.

    ``vip.proxy.build_proxy_map(None)`` reads the ambient proxy environment, and
    ``resolve_url_scheme`` changes behavior when a proxy applies -- it refuses
    the inferred-https -> http downgrade, because the raw-socket TLS-listener
    tiebreak bypasses the proxy and so cannot speak to the path VIP would take.
    Without this, running the selftests on a machine with ``HTTP_PROXY``
    exported flips that branch under a dozen scheme-resolution tests that never
    mention proxies, and their probes attempt real connections through it.

    Autouse and package-wide on purpose: any test that constructs a client,
    resolves a URL, or loads a config can reach the proxy layer, so opting in
    per-test would just recreate the gap. Tests that *are* about proxy behavior
    set the variables they need via ``monkeypatch.setenv``, which still works --
    this fixture runs first and only removes what it did not put there.

    Clearing the variables is necessary but not sufficient. httpx resolves them
    through ``urllib.request.getproxies``, which on darwin is
    ``getproxies_environment() or getproxies_macosx_sysconf()`` -- with the
    environment cleared it falls straight through to whatever proxy is set in
    System Settings, so on a corporate-managed Mac the isolation would silently
    do nothing. Pin httpx's lookup to the environment-only variant, which is what
    ``getproxies`` already is on Linux, so the two platforms behave the same and
    tests that deliberately ``monkeypatch.setenv`` a proxy still work.

    See ``selftests/test_proxy_env_isolation.py`` for the guard on this fixture.
    """
    from urllib.request import getproxies_environment

    for var in _PROXY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("httpx._utils.getproxies", getproxies_environment)


@pytest.fixture()
def pytester(pytester):
    """pytester that disables pytest-playwright for nested in-process runs.

    pytest-playwright (>=0.8.0) wraps every test in a soft-assertion scope via
    its ``pytest_runtest_call`` hook.  Our plugin integration tests run an inner
    pytest session in-process with ``pytester``; that inner session would enter a
    second scope while the outer selftest is still inside one, failing with
    "nested soft assertion scopes are not supported".  The inner sessions never
    use Playwright, so disable the plugin for them.  Subprocess runs start a
    fresh process and are unaffected, so only the in-process path is patched.
    """
    run_inprocess = pytester.runpytest_inprocess

    def runpytest_inprocess(*args, **kwargs):
        return run_inprocess("-p", "no:playwright", *args, **kwargs)

    pytester.runpytest_inprocess = runpytest_inprocess
    return pytester


@pytest.fixture()
def tmp_toml(tmp_path: Path):
    """Helper that writes a TOML string to a temp file and returns the path."""

    def _write(content: str) -> Path:
        p = tmp_path / "vip.toml"
        p.write_text(content)
        return p

    return _write


@pytest.fixture()
def sample_results_json(tmp_path: Path) -> Path:
    """Write a sample results.json and return its path."""
    import json

    data = {
        "generated_at": "2026-01-15T12:00:00+00:00",
        "deployment_name": "Selftest Deployment",
        "exit_status": 0,
        "products": {
            "connect": {
                "enabled": True,
                "url": "https://connect.example.com",
                "version": "2024.09.0",
                "configured": True,
            },
            "workbench": {
                "enabled": False,
                "url": "",
                "version": None,
                "configured": False,
            },
            "package_manager": {
                "enabled": True,
                "url": "https://pm.example.com",
                "version": None,
                "configured": True,
            },
        },
        "results": [
            {
                "nodeid": "tests/connect/test_auth.py::test_connect_login_ui",
                "outcome": "passed",
                "duration": 1.23,
                "longrepr": None,
                "markers": ["connect"],
            },
            {
                "nodeid": "tests/connect/test_auth.py::test_connect_login_api",
                "outcome": "passed",
                "duration": 0.45,
                "longrepr": None,
                "markers": ["connect"],
            },
            {
                "nodeid": "tests/workbench/test_auth.py::test_workbench_login",
                "outcome": "skipped",
                "duration": 0.0,
                "longrepr": "Workbench is not configured",
                "markers": ["workbench"],
            },
            {
                "nodeid": "tests/prerequisites/test_components.py::test_connect_reachable",
                "outcome": "passed",
                "duration": 0.12,
                "longrepr": None,
                "markers": ["prerequisites"],
            },
            {
                "nodeid": "tests/security/test_https.py::test_connect_https",
                "outcome": "failed",
                "duration": 0.8,
                "longrepr": "AssertionError: HTTP not redirected",
                "concise_error": "test_connect_https: HTTP not redirected",
                "markers": ["security"],
            },
        ],
    }
    p = tmp_path / "results.json"
    p.write_text(json.dumps(data))
    return p


_SKIP_STATUSES = frozenset({"skipped", "na_version", "unproven"})


def matrix_from_statuses(statuses: dict[str, list[str]]):
    """Build a TraceabilityMatrix from {control_id: [scenario status, ...]}.

    One TestResult per status, tagged `control-<id>`. A status of "na_version"
    is written as a version-gated skip, and "unproven" as an attested one,
    which is how the plugin records each.
    """
    from vip.reporting import ReportData, TestResult
    from vip.traceability import ControlSpec, build_traceability_matrix

    results = []
    for control_id, control_statuses in statuses.items():
        for i, status in enumerate(control_statuses):
            results.append(
                TestResult(
                    nodeid=f"test_{control_id}.py::test_{i}",
                    outcome="skipped" if status in _SKIP_STATUSES else status,
                    na_version=status == "na_version",
                    unproven=status == "unproven",
                    markers=[f"control-{control_id}"],
                )
            )
    controls = {
        cid: ControlSpec(control_id=cid, description=f"control {cid}", verification="automated")
        for cid in statuses
    }
    return build_traceability_matrix(ReportData(results=results), controls)
