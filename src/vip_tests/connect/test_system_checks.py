"""Step definitions for Connect system checks tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pytest_bdd import scenario, then, when

_REDACTED = "[redacted]"


def _redact_license_outputs(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a copy of *results* with output/error redacted for license checks.

    Connect system check results for license-related checks may include the
    actual license key in their ``output`` or ``error`` fields.  We replace
    those values before writing the artifact so that license keys never appear
    in the report.
    """
    redacted = []
    for r in results:
        group_name = (r.get("group") or {}).get("name", "")
        test_name = (r.get("test") or {}).get("name", "")
        if "license" in group_name.lower() or "license" in test_name.lower():
            r = {**r, "output": _REDACTED, "error": _REDACTED}
        redacted.append(r)
    return redacted


@scenario(
    "test_system_checks.feature",
    "Connect system checks can be run and the report downloaded",
)
def test_connect_system_checks():
    pass


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@when("I trigger a new system check run via the Connect API", target_fixture="system_check")
def trigger_system_check(connect_client):
    return connect_client.run_system_check()


@then("the system check report is returned")
def check_report_returned(system_check):
    assert system_check is not None, "System check API returned no result"
    assert "id" in system_check, (
        f"System check response missing 'id' field. Got: {list(system_check.keys())}"
    )


@then("I can download the system check report artifact")
def download_report_artifact(connect_client, system_check, pytestconfig):
    check_id = system_check["id"]
    completed_run = connect_client.wait_for_system_check(check_id)
    assert completed_run is not None, (
        f"Waiting for system check id={check_id!r} returned no run details"
    )
    assert completed_run.get("status") == "done", (
        "System check did not complete before fetching results. "
        f"id={check_id!r}, final status={completed_run.get('status')!r}"
    )
    results = connect_client.get_system_check_results(check_id)
    assert results, f"System check results for id={check_id!r} were empty"

    # Persist alongside results.json so the Quarto report can embed it.
    # Redact license check output/error before writing so that license keys
    # never appear in the saved artifact or the rendered report.
    vip_report = pytestconfig.getoption("--vip-report")
    if vip_report:
        safe_results = {
            **results,
            "results": _redact_license_outputs(results.get("results", [])),
        }
        artifact_path = Path(vip_report).parent / "connect_system_checks.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(safe_results, indent=2) + "\n",
            encoding="utf-8",
        )
