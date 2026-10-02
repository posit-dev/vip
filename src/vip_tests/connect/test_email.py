"""Step definitions for Connect email tests."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenario, then, when


@scenario("test_email.feature", "Connect can send a test email")
def test_send_email():
    pass


@given("email delivery is enabled")
def email_is_enabled(email_enabled):
    if not email_enabled:
        pytest.skip("Email is not enabled in vip.toml")


@when("I send a test email via the Connect API", target_fixture="email_sent")
def send_test_email(connect_client):
    # The endpoint is admin-only and Connect sends the test message to the API
    # key owner's address, so the user needs to be an administrator with one.
    user = connect_client.current_user()
    if user.get("user_role") != "administrator":
        pytest.skip("Sending a test email requires an administrator API key")
    if not user.get("email"):
        pytest.skip("Current API user has no email address configured")
    # Raises on any non-2xx (e.g. 4xx for a mailer Connect cannot use), which
    # fails the scenario.
    connect_client.send_test_email()
    return True


@then("the test email is accepted by Connect")
def email_accepted(email_sent):
    assert email_sent, "Connect did not accept the test email request"
