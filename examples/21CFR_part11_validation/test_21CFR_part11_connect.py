"""Step definitions for the 21 CFR Part 11 example's Connect scenarios.

Every @scenario function carries a literal @pytest.mark.connect decorator:
feature-level Gherkin tags alone do not drive VIP's auto-skip in extension
directories.
"""

import pytest
from part11_refusal import assert_refused
from pytest_bdd import given, scenario, then, when


@pytest.mark.connect
@scenario(
    "test_21CFR_part11_connect.feature",
    "Publishing content is recorded with an actor and a timestamp",
)
def test_audit_trail_publish():
    pass


@pytest.mark.connect
@scenario("test_21CFR_part11_connect.feature", "A privileged action requires authorisation")
def test_privileged_action_denied():
    pass


@pytest.mark.connect
@scenario("test_21CFR_part11_connect.feature", "The audit log does not offer a deletion method")
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
def request_privileged_endpoint(connect_client, connect_privileged_endpoint):
    return connect_client.unauthenticated_status(connect_privileged_endpoint)


@then("the request is refused")
def request_refused(unauthenticated_status):
    assert_refused(unauthenticated_status)


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
