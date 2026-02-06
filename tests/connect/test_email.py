"""Step definitions for Connect email tests."""

from __future__ import annotations

import pytest
from pytest_bdd import scenario, given, when, then


@scenario("test_email.feature", "Connect can send a test email")
def test_send_email():
    pass


@given("Connect is accessible at the configured URL")
def connect_accessible(connect_client):
    assert connect_client is not None


@given("email delivery is enabled")
def email_is_enabled(email_enabled):
    if not email_enabled:
        pytest.skip("Email is not enabled in vip.toml")


@when("I send a test email via the Connect API", target_fixture="email_result")
def send_test_email(connect_client):
    user = connect_client.current_user()
    email = user.get("email")
    if not email:
        pytest.skip("Current API user has no email address configured")
    return connect_client.send_test_email(email)


@then("the email task completes without error")
def email_task_ok(email_result):
    # The send-test-email endpoint returns a task; verify it was accepted.
    assert email_result is not None, "Email API returned no result"
