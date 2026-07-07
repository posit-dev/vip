"""Step definitions for Package Manager binary package serving checks.

These scenarios verify that PPM's precompiled binary paths (Windows .zip,
macOS .tgz, Linux .tar.gz via bin/linux/..., PyPI .whl) are actually served.
A deployment can pass the existing source-only CRAN/PyPI tests while having
broken binary coverage, so these are a distinct, high-value gap to close.

The tests skip gracefully when a CRAN/PyPI repo has no binary packages yet
(404 from the index), and fail only on unexpected error responses (5xx) or
when a 200 is explicitly returned without usable content.
"""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_binary_packages.feature", "CRAN Windows binaries are served")
def test_cran_windows_binaries():
    pass


@scenario("test_binary_packages.feature", "CRAN macOS binaries are served")
def test_cran_macos_binaries():
    pass


@scenario("test_binary_packages.feature", "CRAN Linux binaries are served")
def test_cran_linux_binaries():
    pass


@scenario("test_binary_packages.feature", "PyPI wheel packages are available")
def test_pypi_wheels():
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_cran_repo(pm_client) -> str | None:
    repos = pm_client.list_repos()
    for r in repos:
        if r.get("type") == "cran" or "cran" in r.get("name", "").lower():
            return r["name"]
    return None


def _find_pypi_repo(pm_client) -> str | None:
    repos = pm_client.list_repos()
    for r in repos:
        if r.get("type") == "pypi" or "pypi" in r.get("name", "").lower():
            return r["name"]
    return None


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@given("Package Manager is running")
def pm_running(pm_client):
    assert pm_client is not None, "Package Manager client not configured"
    status = pm_client.health()
    assert status < 400, f"Package Manager returned HTTP {status}"


@when(
    "I request the CRAN Windows binary package index",
    target_fixture="binary_index_result",
)
def request_windows_binary_index(pm_client):
    repo = _find_cran_repo(pm_client)
    if repo is None:
        pytest.skip("No CRAN repository configured in Package Manager")
    found, status = pm_client.cran_windows_binary_index_reachable(repo)
    if not found and status == 404:
        pytest.skip(
            f"Windows binary PACKAGES index not found for repo {repo!r} — "
            "binary packages may not be synced for this platform"
        )
    return found, status


@when(
    "I request the CRAN macOS binary package index",
    target_fixture="binary_index_result",
)
def request_macos_binary_index(pm_client):
    repo = _find_cran_repo(pm_client)
    if repo is None:
        pytest.skip("No CRAN repository configured in Package Manager")
    found, status = pm_client.cran_macos_binary_index_reachable(repo)
    if not found and status == 404:
        pytest.skip(
            f"macOS binary PACKAGES index not found for repo {repo!r} — "
            "binary packages may not be synced for this platform"
        )
    return found, status


@when(
    "I request the CRAN Linux binary package index",
    target_fixture="binary_index_result",
)
def request_linux_binary_index(pm_client):
    repo = _find_cran_repo(pm_client)
    if repo is None:
        pytest.skip("No CRAN repository configured in Package Manager")
    found, status = pm_client.cran_linux_binary_index_reachable(repo)
    if not found and status == 404:
        pytest.skip(
            f"Linux binary PACKAGES index not found for repo {repo!r} — "
            "binary packages may not be synced for this platform"
        )
    return found, status


@when(
    'I check the PyPI repository for wheel files for the "numpy" package',
    target_fixture="binary_index_result",
)
def check_pypi_wheels(pm_client):
    repo = _find_pypi_repo(pm_client)
    if repo is None:
        pytest.skip("No PyPI repository configured in Package Manager")
    found, status = pm_client.pypi_wheel_available(repo, "numpy")
    if not found and status == 404:
        pytest.skip(
            f"PyPI simple index not found for 'numpy' in repo {repo!r} — PyPI may not be synced yet"
        )
    # A 200 index with no wheels is a failure, not a skip: 'numpy' always ships
    # manylinux wheels, so a wheel-less index means binary serving is broken —
    # the exact case this suite exists to catch (matches the CRAN steps and the
    # module docstring's "200 without usable content" contract).
    return found, status


@then("the binary package index is reachable")
def binary_index_is_reachable(binary_index_result):
    found, status = binary_index_result
    assert found, (
        f"Binary package index not served or contains no binaries (HTTP {status}). "
        "Binary serving may be broken for this deployment."
    )
