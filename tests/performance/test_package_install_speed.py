"""Step definitions for package installation speed tests."""

from __future__ import annotations

import time

import httpx
import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_package_install_speed.feature", "CRAN package downloads within acceptable time")
def test_cran_speed():
    pass


@scenario("test_package_install_speed.feature", "PyPI package downloads within acceptable time")
def test_pypi_speed():
    pass


@given("Package Manager is running and has a CRAN repo", target_fixture="cran_repo")
def pm_has_cran(pm_client):
    assert pm_client is not None
    repos = pm_client.list_repos()
    cran = [r for r in repos if r.get("type") == "cran" or "cran" in r.get("name", "").lower()]
    if not cran:
        pytest.skip("No CRAN repo configured in Package Manager")
    return cran[0]


@given("Package Manager is running and has a PyPI repo", target_fixture="pypi_repo")
def pm_has_pypi(pm_client):
    assert pm_client is not None
    repos = pm_client.list_repos()
    pypi = [r for r in repos if r.get("type") == "pypi" or "pypi" in r.get("name", "").lower()]
    if not pypi:
        pytest.skip("No PyPI repo configured in Package Manager")
    return pypi[0]


@when("I download a small CRAN package", target_fixture="download_time")
def download_cran(pm_client, cran_repo):
    # Download the PACKAGES index as a proxy for package download speed.
    url = f"{pm_client.base_url}/{cran_repo['name']}/latest/src/contrib/PACKAGES"
    start = time.monotonic()
    resp = httpx.get(url, timeout=30)
    elapsed = time.monotonic() - start
    resp.raise_for_status()
    return elapsed


@when("I download a small PyPI package", target_fixture="download_time")
def download_pypi(pm_client, pypi_repo):
    url = f"{pm_client.base_url}/{pypi_repo['name']}/latest/simple/pip/"
    start = time.monotonic()
    resp = httpx.get(url, timeout=30)
    elapsed = time.monotonic() - start
    resp.raise_for_status()
    return elapsed


@then("the download completes in under 30 seconds")
def download_fast(download_time):
    assert download_time < 30, f"Download took {download_time:.2f}s (threshold: 30s)"
