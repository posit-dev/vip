"""Step definitions for Connect system checks tests."""

from __future__ import annotations

from pytest_bdd import given, scenario, then, when


@scenario(
    "test_system_checks.feature",
    "Connect system checks can be run and the report downloaded",
)
def test_connect_system_checks():
    pass


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@given("a valid API key is configured")
def api_key_configured(vip_config):
    assert vip_config.connect.api_key, (
        "VIP_CONNECT_API_KEY is not set. Set it in vip.toml or as an environment variable."
    )


@when("I trigger a new system check run via the Connect API", target_fixture="server_check")
def trigger_system_check(connect_client):
    return connect_client.run_server_check()


@then("the system check report is returned")
def check_report_returned(server_check):
    assert server_check is not None, "System check API returned no result"
    assert "id" in server_check, (
        f"System check response missing 'id' field. Got: {list(server_check.keys())}"
    )


@then("I can download the system check report artifact")
def download_report_artifact(connect_client, server_check):
    check_id = server_check["id"]
    report_bytes = connect_client.get_server_check_report(check_id)
    assert report_bytes, f"System check report for id={check_id!r} was empty"
