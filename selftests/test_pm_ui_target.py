"""Selftests for ``ui_target`` / ``_find_ui_target`` in
``src/vip_tests/package_manager/test_ui.py``.

The UI scenarios skip when the deployment has nothing to exercise, and the
reason has to say *which* nothing. ``_find_ui_target`` returned a bare ``{}``
for two unrelated states -- no repo of that ecosystem is configured at all, and
a repo is configured but does not serve the known package -- so the caller
reported both as "repo may not be synced yet". On a deployment with no OpenVSX
repository whatsoever that sent an administrator looking for a stalled sync
that did not exist, while ``test_repos.py`` described the very same deployment
accurately as "No OpenVSX repository configured in Package Manager".

Two files disagreeing about one fact in a single run is the bug. These tests
pin both messages and assert the two modules stay consistent.
"""

from __future__ import annotations

import pytest

from vip_tests.package_manager.test_repos import (
    query_bioconductor,
    query_cran,
    query_openvsx,
    query_pypi,
)
from vip_tests.package_manager.test_ui import ui_target

# ---------------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------------


class FakePMClient:
    """Stand-in for ``PackageManagerClient``; see the twin in
    ``test_pm_repo_selection.py``."""

    def __init__(self, repos, serving=None):
        self._repos = repos
        self._serving = serving or {}
        self.probed: list[tuple[str, str]] = []

    def list_repos(self):
        return self._repos

    def _available(self, repo_name, package):
        self.probed.append((repo_name, package))
        return package in self._serving.get(repo_name, set())

    cran_package_available = _available
    pypi_package_available = _available
    bioconductor_package_available = _available
    openvsx_extension_available = _available


# Ecosystem label, two repo names matching its hint, and its known package.
# Names are deliberately not substrings of each other so an assertion that both
# appear in a message cannot pass on a partial match.
ECOSYSTEMS = [
    pytest.param("CRAN", ["curated-cran", "cran-mirror"], "Matrix", id="cran"),
    pytest.param("PyPI", ["curated-pypi", "pypi-mirror"], "requests", id="pypi"),
    pytest.param(
        "Bioconductor", ["curated-bioc", "bioc-mirror"], "BiocGenerics", id="bioconductor"
    ),
    pytest.param("OpenVSX", ["curated-vsx", "vsx-mirror"], "golang.Go", id="openvsx"),
]

# Maps an ecosystem to the equivalent test_repos.py step, for the
# cross-module consistency check at the bottom.
REPOS_STEP = {
    "CRAN": query_cran,
    "PyPI": query_pypi,
    "Bioconductor": query_bioconductor,
    "OpenVSX": query_openvsx,
}


def _repo(name, type_=""):
    return {"name": name, "type": type_}


def _skip_reason(fn, *args):
    with pytest.raises(pytest.skip.Exception) as exc_info:
        fn(*args)
    return exc_info.value.msg


# ---------------------------------------------------------------------------
# Finding a target
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("ecosystem", "repo_names", "package"), ECOSYSTEMS)
def test_returns_the_repo_that_serves_the_package(ecosystem, repo_names, package):
    client = FakePMClient(
        [_repo(n) for n in repo_names],
        serving={repo_names[1]: {package}},
    )

    target = ui_target(client, ecosystem)

    assert target == {"repo": repo_names[1], "package": package, "ecosystem": ecosystem}


@pytest.mark.parametrize(("ecosystem", "repo_names", "package"), ECOSYSTEMS)
def test_null_repo_name_does_not_crash(ecosystem, repo_names, package):
    """``{"name": null}`` is valid JSON; ``.get("name", "")`` hands back None
    for it and ``.lower()`` then raises, taking the step down with an
    AttributeError instead of skipping."""
    client = FakePMClient(
        [{"name": None, "type": None}, _repo(repo_names[1])],
        serving={repo_names[1]: {package}},
    )

    assert ui_target(client, ecosystem)["repo"] == repo_names[1]


# ---------------------------------------------------------------------------
# The two skip states must be distinguishable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("ecosystem", "repo_names", "package"), ECOSYSTEMS)
def test_nothing_configured_does_not_blame_syncing(ecosystem, repo_names, package):
    """The OpenVSX case from a real run: no repo of this ecosystem exists at
    all, so "may not be synced yet" points at a stalled sync that isn't there."""
    client = FakePMClient([_repo("unrelated-repo")], serving={})

    reason = _skip_reason(ui_target, client, ecosystem)

    assert "configured" in reason
    assert "synced" not in reason, f"nothing is configured, so syncing is not the cause: {reason}"
    assert client.probed == []


@pytest.mark.parametrize(("ecosystem", "repo_names", "package"), ECOSYSTEMS)
def test_configured_but_unserved_names_every_repo_tried(ecosystem, repo_names, package):
    """The other state: repos exist and genuinely may still be syncing. Here
    the reason must name them, so the administrator knows where to look."""
    client = FakePMClient([_repo(n) for n in repo_names], serving={})

    reason = _skip_reason(ui_target, client, ecosystem)

    assert "synced" in reason
    assert package in reason
    for name in repo_names:
        assert name in reason, f"skip reason should name every repo tried: {reason}"


# ---------------------------------------------------------------------------
# Cross-module consistency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("ecosystem", "repo_names", "package"), ECOSYSTEMS)
def test_agrees_with_test_repos_when_nothing_is_configured(ecosystem, repo_names, package):
    """One deployment fact, one explanation. test_ui.py and test_repos.py ran
    in the same session and described an OpenVSX-less server two different
    ways; the "nothing configured" reason must now match verbatim."""
    client = FakePMClient([_repo("unrelated-repo")], serving={})

    ui_reason = _skip_reason(ui_target, client, ecosystem)
    repos_reason = _skip_reason(REPOS_STEP[ecosystem], FakePMClient([_repo("unrelated-repo")]))

    assert ui_reason == repos_reason


@pytest.mark.parametrize(("ecosystem", "repo_names", "package"), ECOSYSTEMS)
def test_agrees_with_test_repos_when_configured_but_unserved(ecosystem, repo_names, package):
    repos = [_repo(n) for n in repo_names]

    ui_reason = _skip_reason(ui_target, FakePMClient(repos), ecosystem)
    repos_reason = _skip_reason(REPOS_STEP[ecosystem], FakePMClient(repos))

    assert ui_reason == repos_reason
