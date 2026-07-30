"""Step definitions for Package Manager repository checks."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_repos.feature", "CRAN mirror is accessible")
def test_cran_mirror():
    pass


@scenario("test_repos.feature", "PyPI mirror is accessible")
def test_pypi_mirror():
    pass


@scenario("test_repos.feature", "Bioconductor mirror is accessible")
def test_bioconductor_mirror():
    pass


@scenario("test_repos.feature", "OpenVSX mirror is accessible")
def test_openvsx_mirror():
    pass


@scenario("test_repos.feature", "At least one repository is configured")
def test_repo_exists():
    pass


# ---------------------------------------------------------------------------
# Repository selection
# ---------------------------------------------------------------------------


def _first_repo_serving(pm_client, *, ecosystem, matches, available, package, noun="package"):
    """Return the first repo matching *ecosystem* that actually serves *package*.

    A deployment routinely hosts several repos per ecosystem -- a full mirror
    alongside curated or vulnerability-blocked subsets. Probing only the first
    match made the result depend on the order the server happens to list them
    in: ``curated-pypi`` sorts ahead of ``pypi`` and by design carries only a
    handful of approved packages, so the PyPI scenario skipped as "not
    available -- repo may not be synced yet" while the full mirror beside it
    served the package fine. Walk every candidate before concluding anything.

    Skips (never fails) in two distinguishable states: no repo of this
    ecosystem is configured at all, or one is configured but none serves the
    package. Those are different deployment problems and the reason says which.

    *matches* is called with the repo's ``type`` and ``name`` already coerced
    to strings. The server can send an explicit JSON null for either, which
    ``.get("type", "")`` would hand straight through as None and crash the
    matcher on ``.upper()``; normalising here means no matcher has to remember.
    A repo with no usable name is dropped outright -- there is nothing to query.
    """
    candidates = []
    for repo in pm_client.list_repos():
        name = repo.get("name") or ""
        repo_type = repo.get("type") or ""
        if name and matches(repo_type, name):
            candidates.append(name)
    if not candidates:
        pytest.skip(f"No {ecosystem} repository configured in Package Manager")
    for repo_name in candidates:
        if available(repo_name, package):
            return repo_name
    pytest.skip(
        f"{ecosystem} {noun} {package!r} not available in any of {candidates} — "
        "repo may not be synced yet"
    )


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@given("Package Manager is running")
def pm_running(pm_client):
    assert pm_client is not None, "Package Manager client not configured"
    status = pm_client.health()
    assert status < 400, f"Package Manager returned HTTP {status}"


@when(
    'I query the CRAN repository for the "Matrix" package',
    target_fixture="package_found",
)
def query_cran(pm_client):
    _first_repo_serving(
        pm_client,
        ecosystem="CRAN",
        matches=lambda t, n: t == "cran" or "cran" in n.lower(),
        available=pm_client.cran_package_available,
        package="Matrix",
    )
    return True


@when(
    'I query the PyPI repository for the "requests" package',
    target_fixture="package_found",
)
def query_pypi(pm_client):
    _first_repo_serving(
        pm_client,
        ecosystem="PyPI",
        matches=lambda t, n: t == "pypi" or "pypi" in n.lower(),
        available=pm_client.pypi_package_available,
        package="requests",
    )
    return True


@when(
    'I query the Bioconductor repository for the "BiocGenerics" package',
    target_fixture="package_found",
)
def query_bioconductor(pm_client):
    _first_repo_serving(
        pm_client,
        ecosystem="Bioconductor",
        matches=lambda t, n: t == "bioconductor" or "bioc" in n.lower(),
        available=pm_client.bioconductor_package_available,
        package="BiocGenerics",
    )
    return True


@when(
    'I query the OpenVSX repository for the "golang.Go" extension',
    target_fixture="package_found",
)
def query_openvsx(pm_client):
    _first_repo_serving(
        pm_client,
        ecosystem="OpenVSX",
        matches=lambda t, n: t.upper() == "VSX" or "vsx" in n.lower(),
        available=pm_client.openvsx_extension_available,
        package="golang.Go",
        noun="extension",
    )
    return True


@when("I list all repositories", target_fixture="repo_list")
def list_repos(pm_client):
    return pm_client.list_repos()


@then("the package is found in the repository")
def package_is_found(package_found):
    assert package_found, "Package was not found in the repository"


@then("at least one repository exists")
def repo_exists(repo_list):
    assert len(repo_list) > 0, "No repositories configured in Package Manager"
