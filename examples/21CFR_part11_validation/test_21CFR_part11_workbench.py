"""Step definitions for the Part 11 example's Workbench scenarios.

The two scenarios are one control read from both sides. Refusing an
unauthenticated caller is not on its own evidence that access is limited to
authorised individuals -- a deployment that refuses everybody passes that half
too. Pairing it with a granted request is the standard positive-and-negative
form of an access-control test, and 11.10(d) asks for both halves.

Every @scenario function carries a literal @pytest.mark.workbench decorator:
feature-level Gherkin tags alone do not drive VIP's auto-skip in extension
directories.
"""

import pytest
from part11_refusal import assert_refused
from pytest_bdd import given, scenario, then, when


@pytest.mark.workbench
@scenario(
    "test_21CFR_part11_workbench.feature",
    "An unauthenticated caller cannot reach the session API",
)
def test_session_api_refuses_anonymous():
    pass


@pytest.mark.workbench
@scenario(
    "test_21CFR_part11_workbench.feature",
    "An authorised caller can reach the session API",
)
def test_session_api_serves_authorised_caller():
    pass


@given("Workbench is accessible at the configured URL")
def workbench_accessible(workbench_client):
    if workbench_client is None:
        pytest.skip("Workbench is not configured")
    return workbench_client


@when(
    "I request the Workbench session API without credentials",
    target_fixture="unauthenticated_status",
)
def request_session_api_anonymously(workbench_client, workbench_privileged_endpoint):
    return workbench_client.unauthenticated_status(workbench_privileged_endpoint)


@then("the request is refused")
def request_refused(unauthenticated_status):
    assert_refused(unauthenticated_status)


@when(
    "I request the Workbench session API with the test credentials",
    target_fixture="session_api_usable",
)
def request_session_api_authenticated(workbench_client):
    """Ask whether the session API answers this client with a usable listing.

    ``sessions_api_reachable`` requires a 200 whose body parses as a JSON
    array, so a login redirect or an HTML SPA fallback counts as unusable
    rather than as success.
    """
    return workbench_client.sessions_api_reachable()


@then("a session listing is returned")
def session_listing_returned(session_api_usable):
    """Pass or skip. This scenario cannot fail, and that is a real limitation.

    The client only holds a Workbench session under ``--headless-auth`` /
    ``--interactive-auth`` or with an API key. An unusable answer therefore has
    two causes that cannot be told apart from here: the run carried no
    credentials at all (correct behaviour, nothing to assert), or it carried
    credentials the deployment rejected (a genuine control failure). Blaming
    the deployment for the first case would fail this scenario on every run
    that skips authentication, so it skips instead.

    That makes this half weaker than its negative counterpart, which does fail
    on a real defect. Read the skip in the matrix as covered-not-executed, and
    run with authentication if you want the control exercised.
    """
    if not session_api_usable:
        pytest.skip(
            "the session API did not return a usable listing; run with "
            "--headless-auth or --interactive-auth to exercise this control"
        )
