"""Selftests for repository selection in
``src/vip_tests/package_manager/test_repos.py``.

A deployment commonly hosts several repos per ecosystem -- a full mirror
alongside curated or vulnerability-blocked subsets (``pypi``,
``curated-pypi``, ``pypi-vulns-blocked``). Selecting only the *first*
name-matched repo made the check depend on alphabetical ordering: on a real
deployment ``curated-pypi`` sorts first and by design carries only a handful
of approved packages, so the PyPI scenario skipped with "'requests' not
available -- repo may not be synced yet" while the ``pypi`` mirror right next
to it served the package fine. That is a false skip: it silently drops
coverage on a healthy deployment and reports an inaccurate reason.

Every ecosystem step must therefore probe each candidate repo until one
serves the package, the way ``query_openvsx`` already did.
"""

from __future__ import annotations

import pytest

from vip_tests.package_manager.test_repos import (
    query_bioconductor,
    query_cran,
    query_openvsx,
    query_pypi,
)

# ---------------------------------------------------------------------------
# Fake client
# ---------------------------------------------------------------------------


class FakePMClient:
    """Minimal stand-in for ``PackageManagerClient``.

    *repos* is the ``list_repos`` payload; *serving* maps repo name -> the set
    of packages that repo serves. ``probed`` records every availability call so
    a test can assert the step actually walked past a non-serving repo.
    """

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


def _repo(name, type_=""):
    return {"name": name, "type": type_}


def _run_expecting_no_skip(step, client):
    """Call *step*, converting an unexpected ``pytest.skip`` into a failure.

    Letting the skip propagate would mark *this selftest* as skipped rather
    than failed -- the regression these tests exist to catch would sail
    through green. Catch it and fail loudly with the reason instead.
    """
    try:
        return step(client)
    except pytest.skip.Exception as exc:
        pytest.fail(f"step skipped instead of finding the package: {exc.msg}")


# Each ecosystem's step function, the repo names that match its hint, and the
# package it looks for -- so one parametrized body covers all four.
#
# The two repo names per ecosystem are deliberately NOT substrings of one
# another ("cran-mirror", not "cran", alongside "curated-cran"): the skip-reason
# assertion below checks that every probed repo is named in the message, and a
# substring would satisfy that check even when only the first repo was listed.
ECOSYSTEMS = [
    pytest.param(query_cran, ["curated-cran", "cran-mirror"], "Matrix", "CRAN", id="cran"),
    pytest.param(query_pypi, ["curated-pypi", "pypi-mirror"], "requests", "PyPI", id="pypi"),
    pytest.param(
        query_bioconductor,
        ["curated-bioc", "bioc-mirror"],
        "BiocGenerics",
        "Bioconductor",
        id="bioconductor",
    ),
    pytest.param(
        query_openvsx, ["curated-vsx", "vsx-mirror"], "golang.Go", "OpenVSX", id="openvsx"
    ),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("step", "repo_names", "package", "label"), ECOSYSTEMS)
def test_falls_through_to_a_later_repo_that_serves_the_package(step, repo_names, package, label):
    """The regression: the package lives in the second matching repo.

    The first repo sorts earlier and does not carry the package (a curated
    subset), so stopping at ``repos[0]`` produced a false skip.
    """
    client = FakePMClient(
        [_repo(n) for n in repo_names],
        serving={repo_names[1]: {package}},
    )

    assert _run_expecting_no_skip(step, client) is True
    assert client.probed == [(repo_names[0], package), (repo_names[1], package)]


@pytest.mark.parametrize(("step", "repo_names", "package", "label"), ECOSYSTEMS)
def test_stops_probing_once_a_repo_serves_the_package(step, repo_names, package, label):
    """No wasted requests: the walk short-circuits on the first hit."""
    client = FakePMClient(
        [_repo(n) for n in repo_names],
        serving={n: {package} for n in repo_names},
    )

    assert _run_expecting_no_skip(step, client) is True
    assert client.probed == [(repo_names[0], package)]


@pytest.mark.parametrize(("step", "repo_names", "package", "label"), ECOSYSTEMS)
def test_skips_when_no_repo_serves_the_package(step, repo_names, package, label):
    """Still a skip when the package is genuinely absent everywhere -- but the
    reason must name every repo tried, not just the first, so the message
    doesn't misattribute an unsynced mirror."""
    client = FakePMClient([_repo(n) for n in repo_names], serving={})

    with pytest.raises(pytest.skip.Exception) as exc_info:
        step(client)

    message = exc_info.value.msg
    assert package in message
    for name in repo_names:
        assert name in message, f"skip reason should name every repo tried: {message}"


@pytest.mark.parametrize(("step", "repo_names", "package", "label"), ECOSYSTEMS)
def test_skips_when_no_repo_of_that_ecosystem_is_configured(step, repo_names, package, label):
    """A deployment with no repo of this ecosystem skips with a distinct
    reason -- "none configured" is a different state from "configured but not
    synced", and conflating them hides a misconfiguration."""
    client = FakePMClient([_repo("unrelated-repo")], serving={})

    with pytest.raises(pytest.skip.Exception) as exc_info:
        step(client)

    assert "configured" in exc_info.value.msg
    assert client.probed == []


@pytest.mark.parametrize(("step", "repo_names", "package", "label"), ECOSYSTEMS)
def test_matches_on_declared_type_not_only_the_name_hint(step, repo_names, package, label):
    """A repo whose name carries no hint is still a candidate when the server
    declares a matching ``type``, so a deployment free to name its repos
    anything is not silently skipped."""
    declared_type = {
        "CRAN": "cran",
        "PyPI": "pypi",
        "Bioconductor": "bioconductor",
        "OpenVSX": "VSX",
    }[label]
    client = FakePMClient(
        [_repo("packages", declared_type)],
        serving={"packages": {package}},
    )

    assert _run_expecting_no_skip(step, client) is True


# ---------------------------------------------------------------------------
# Malformed repo payloads
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("step", "repo_names", "package", "label"), ECOSYSTEMS)
def test_explicit_null_type_does_not_crash_the_step(step, repo_names, package, label):
    """``{"type": null}`` is valid JSON the server can send, and ``.get("type",
    "")`` returns None for it rather than the default -- which the OpenVSX
    matcher's ``.upper()`` turned into an AttributeError, crashing repo
    selection instead of skipping or passing. The name hint must still match."""
    client = FakePMClient(
        [{"name": repo_names[1], "type": None}],
        serving={repo_names[1]: {package}},
    )

    assert _run_expecting_no_skip(step, client) is True


@pytest.mark.parametrize(("step", "repo_names", "package", "label"), ECOSYSTEMS)
def test_explicit_null_name_is_skipped_over(step, repo_names, package, label):
    """A repo with a null name cannot be queried, so it must be dropped rather
    than probed as the empty string."""
    client = FakePMClient(
        [{"name": None, "type": None}, {"name": repo_names[1], "type": None}],
        serving={repo_names[1]: {package}},
    )

    assert _run_expecting_no_skip(step, client) is True
    assert client.probed == [(repo_names[1], package)]


@pytest.mark.parametrize(("step", "repo_names", "package", "label"), ECOSYSTEMS)
def test_repo_payload_missing_both_keys_is_ignored(step, repo_names, package, label):
    client = FakePMClient([{}], serving={})

    with pytest.raises(pytest.skip.Exception) as exc_info:
        step(client)

    assert "configured" in exc_info.value.msg
    assert client.probed == []
