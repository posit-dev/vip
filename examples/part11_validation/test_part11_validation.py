"""Step definitions for the Part 11 example.

Every @scenario function carries a literal @pytest.mark.connect decorator:
feature-level Gherkin tags alone do not drive VIP's auto-skip in extension
directories.
"""

import pytest
from pytest_bdd import given, scenario, then, when


@pytest.mark.connect
@scenario(
    "test_part11_validation.feature",
    "Publishing content is recorded with an actor and a timestamp",
)
def test_audit_trail_publish():
    pass


@pytest.mark.connect
@scenario("test_part11_validation.feature", "A privileged action requires authorisation")
def test_privileged_action_denied():
    pass


@pytest.mark.connect
@scenario("test_part11_validation.feature", "The audit log does not offer a deletion method")
def test_audit_log_not_deletable():
    pass


@given("Connect is accessible at the configured URL")
def connect_accessible(connect_client):
    if connect_client is None:
        pytest.skip("Connect is not configured")
    return connect_client


@when("I list recent audit log entries", target_fixture="audit_entries")
def list_audit_entries(connect_client):
    entries = connect_client.list_audit_logs()
    if entries is None:
        pytest.skip("this deployment does not expose an audit log endpoint")
    return entries


@then("each entry records an actor and a timestamp")
def entries_have_actor_and_timestamp(audit_entries):
    if not audit_entries:
        pytest.skip("no audit entries to inspect")
    for entry in audit_entries:
        assert entry.get("user_id") or entry.get("user_description"), (
            f"audit entry has no actor: {entry}"
        )
        assert entry.get("time") or entry.get("timestamp"), f"audit entry has no timestamp: {entry}"


@when(
    "I request a privileged administrative endpoint without credentials",
    target_fixture="unauthenticated_status",
)
def request_privileged_endpoint(connect_client, privileged_endpoint):
    return connect_client.unauthenticated_status(privileged_endpoint)


@then("the request is refused")
def request_refused(unauthenticated_status):
    """Assert the control that matters: unauthenticated access is not GRANTED.

    A bare ``in (401, 403)`` check fails a correctly-secured deployment fronted
    by OIDC/SAML or a forward-auth gateway, which answers an unauthenticated
    API call with a redirect (302/307) to a login page rather than a 401/403 --
    a deployment shape VIP explicitly supports. That redirect IS a refusal:
    the request never reached the privileged endpoint unauthenticated.

    So the assertion is inverted: any 2xx is the one outcome that is actually
    unsafe (credentials were not required), and that is what fails the
    scenario. 401/403 and any 3xx are accepted as refusals. Every other status
    is handled explicitly rather than falling through a bare comparison: a 5xx
    means the deployment errored, which is not evidence the access control
    works (or that it's broken) -- it is inconclusive, so the scenario fails
    with a message that says so rather than passing silently. Anything else
    unrecognized also fails explicitly, so a new status code shows up as a
    named failure instead of a silent pass.
    """
    status = unauthenticated_status
    if 200 <= status < 300:
        pytest.fail(
            f"unauthenticated request was granted (status {status}); access control is not enforced"
        )
    if status in (401, 403) or 300 <= status < 400:
        return
    if 500 <= status < 600:
        pytest.fail(
            f"deployment returned {status} for an unauthenticated request; a server "
            "error is not evidence of a working access control"
        )
    pytest.fail(f"unexpected status {status}; cannot confirm the request was refused")


@when("I ask which methods the audit log endpoint allows", target_fixture="allowed_methods")
def audit_log_allowed_methods(connect_client):
    """Read the advertised method set. Never issue a mutating request.

    This scenario must not DELETE a real audit record to prove records cannot
    be deleted -- in a regulated deployment that record is the evidence, and
    destroying it is the exact harm this control exists to prevent.
    """
    methods = connect_client.audit_log_allowed_methods()
    if methods is None:
        pytest.skip("this deployment does not advertise allowed methods for the audit log")
    return methods


@then("deletion is not among them")
def deletion_not_offered(allowed_methods):
    assert "DELETE" not in allowed_methods, (
        f"audit log endpoint advertises DELETE; allowed methods: {sorted(allowed_methods)}"
    )
