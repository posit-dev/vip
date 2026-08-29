"""Step definitions for the Part 11 example's Package Manager scenarios.

Every @scenario function carries a literal @pytest.mark.package_manager
decorator: feature-level Gherkin tags alone do not drive VIP's auto-skip in
extension directories.
"""

import pytest
from pytest_bdd import given, scenario, then, when


@pytest.mark.package_manager
@scenario(
    "test_21CFR_part11_packagemanager.feature",
    "The deployment serves a defined set of repositories",
)
def test_package_source_controlled():
    pass


@pytest.mark.package_manager
@scenario(
    "test_21CFR_part11_packagemanager.feature",
    "A past package set can still be retrieved",
)
def test_package_environment_reproducible():
    pass


@given("Package Manager is accessible at the configured URL")
def pm_accessible(pm_client):
    if pm_client is None:
        pytest.skip("Package Manager is not configured")
    return pm_client


@when("I list the configured repositories", target_fixture="repositories")
def list_repositories(pm_client):
    return pm_client.list_repos()


@then("at least one repository is served, and each one is named")
def repositories_are_named(repositories):
    """Evidence for 11.10(a): the package supply is defined rather than ad hoc.

    A deployment whose analyses install from the open internet cannot say what
    software produced a record. One named repository is the weakest form of
    that evidence, and it is deliberately all this scenario claims -- whether
    the repository holds the right packages is a question for your own
    qualification tests, not for a control-mapping example.
    """
    assert repositories, "Package Manager serves no repositories"
    for repo in repositories:
        assert repo.get("name"), f"repository has no name: {repo}"


@when("I request the package index for the validated snapshot", target_fixture="snapshot_result")
def request_snapshot_index(pm_client, validated_repo_name, validated_snapshot):
    """Read a dated index. Never mutate the repository.

    Package Manager's contribution to 11.10(a) is that a package set can be
    addressed at a point in time, so an analysis run last year can be rebuilt
    from the same inputs today.
    """
    return pm_client.snapshot_index_reachable(validated_repo_name, validated_snapshot)


@then("the snapshot's index is served")
def snapshot_index_served(snapshot_result, validated_repo_name, validated_snapshot):
    """Separate "this deployment cannot answer" from "this deployment answered wrong".

    A 404 means snapshots are switched off, or that date predates the
    repository -- a configuration fact about the deployment, not a failed
    control, so the scenario skips. A 5xx means the server broke while
    answering, which fails. Read the skip in the matrix as
    covered-not-executed: it is not evidence the control holds.
    """
    found, status = snapshot_result
    if found:
        return
    if status == 404:
        pytest.skip(
            f"no snapshot {validated_snapshot} for repository {validated_repo_name}; "
            "snapshots may be disabled, or the date may predate the repository"
        )
    assert found, (
        f"snapshot {validated_snapshot} of repository {validated_repo_name} "
        f"did not serve a package index (status {status})"
    )
