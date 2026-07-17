"""Step definitions for Connect system checks tests."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pytest_bdd import scenario, then, when

_REDACTED = "[redacted]"

# Posit license keys are seven hyphen-separated groups of four uppercase
# alphanumerics (e.g. ABCD-1234-EFGH-5678-IJKL-9012-MNOP). Scrub anything of
# this shape so a key never reaches the report even if it surfaces in a check
# whose name does not mention "license".
_LICENSE_KEY_RE = re.compile(r"\b[A-Z0-9]{4}(?:-[A-Z0-9]{4}){6}\b")

# Connect session checks (e.g. rmarkdown-sandbox) echo the session job key on a
# line like "[connect-session] Job Key: ZbPLlfduV5wlvLb1". The key itself has no
# fixed shape, so anchor on the "Job Key:" label and redact only the token that
# follows, leaving the rest of the diagnostic log intact.
_JOB_KEY_RE = re.compile(r"(Job Key:\s*)(\S+)", re.IGNORECASE)


def _scrub_license_keys(value: Any) -> Any:
    """Replace Posit-license-key-shaped tokens in *value* if it is a string."""
    if isinstance(value, str):
        return _LICENSE_KEY_RE.sub(_REDACTED, value)
    return value


def _scrub_job_keys(value: Any) -> Any:
    """Redact the token following a ``Job Key:`` label if *value* is a string."""
    if isinstance(value, str):
        return _JOB_KEY_RE.sub(rf"\g<1>{_REDACTED}", value)
    return value


def _scrub_secrets(value: Any) -> Any:
    """Scrub license keys and session job keys from a string value."""
    return _scrub_job_keys(_scrub_license_keys(value))


def _redact_sensitive_outputs(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a copy of *results* with sensitive data removed.

    Connect system check results echo the running configuration, and some checks
    print secrets: the license checks (e.g. ``connect-license`` runs
    ``license-manager status``) print the activated product key, and session
    checks (e.g. ``rmarkdown-sandbox``) print the connect-session job key.
    Layers guard against those reaching the saved artifact or rendered report:

    * Any check whose group or test name mentions "license" has its ``output``
      and ``error`` fully redacted.
    * Every other ``output``/``error`` is scrubbed for anything shaped like a
      Posit license key or following a ``Job Key:`` label, as defense in depth
      for unexpectedly named checks.

    The input is not mutated.
    """
    redacted = []
    for r in results:
        group_name = (r.get("group") or {}).get("name", "")
        test_name = (r.get("test") or {}).get("name", "")
        if "license" in group_name.lower() or "license" in test_name.lower():
            r = {**r, "output": _REDACTED, "error": _REDACTED}
        else:
            scrubbed = {k: _scrub_secrets(r[k]) for k in ("output", "error") if k in r}
            r = {**r, **scrubbed}
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
            "results": _redact_sensitive_outputs(results.get("results") or []),
        }
        artifact_path = Path(vip_report).parent / "connect_system_checks.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(
            json.dumps(safe_results, indent=2) + "\n",
            encoding="utf-8",
        )
