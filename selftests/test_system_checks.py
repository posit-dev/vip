"""Tests for the secret redaction helpers in test_system_checks."""

from __future__ import annotations

import pytest

from vip_tests.connect.test_system_checks import (
    _REDACTED,
    _redact_sensitive_outputs,
    _scrub_job_keys,
    _scrub_license_keys,
)

# A realistic Posit product key shape (seven groups of four).
_SAMPLE_KEY = "A33R-D4BT-JFGA-NBA3-A6VF-AUGQ-PSTA"

# A Connect session job key as printed by the connect-session process, e.g.
# "[connect-session] Job Key: ZbPLlfduV5wlvLb1".
_SAMPLE_JOB_KEY = "ZbPLlfduV5wlvLb1"


def _make_result(group: str, test: str, output: str = "data", error: str = "") -> dict:
    return {"group": {"name": group}, "test": {"name": test}, "output": output, "error": error}


class TestRedactLicenseOutputs:
    def test_license_group_is_redacted(self):
        results = [_make_result("License", "activation check", output="key=SECRET")]
        redacted = _redact_sensitive_outputs(results)
        assert redacted[0]["output"] == _REDACTED
        assert redacted[0]["error"] == _REDACTED

    def test_license_in_test_name_is_redacted(self):
        results = [_make_result("System", "license validity", output="key=SECRET")]
        redacted = _redact_sensitive_outputs(results)
        assert redacted[0]["output"] == _REDACTED
        assert redacted[0]["error"] == _REDACTED

    def test_connect_license_check_is_redacted(self):
        # This is the real check that leaked the key in the example report.
        results = [_make_result("server", "connect-license", output=f"Product-Key: {_SAMPLE_KEY}")]
        redacted = _redact_sensitive_outputs(results)
        assert redacted[0]["output"] == _REDACTED

    def test_non_license_check_is_not_redacted(self):
        results = [_make_result("Database", "connection", output="ok", error="")]
        redacted = _redact_sensitive_outputs(results)
        assert redacted[0]["output"] == "ok"
        assert redacted[0]["error"] == ""

    def test_case_insensitive_group_match(self):
        results = [_make_result("LICENSE", "check", output="secret")]
        redacted = _redact_sensitive_outputs(results)
        assert redacted[0]["output"] == _REDACTED

    def test_case_insensitive_test_name_match(self):
        results = [_make_result("System", "LICENSE_CHECK", output="secret")]
        redacted = _redact_sensitive_outputs(results)
        assert redacted[0]["output"] == _REDACTED

    def test_mixed_results_selective_redaction(self):
        results = [
            _make_result("License", "key", output="ABC-123"),
            _make_result("Runtime", "r_version", output="4.3.1"),
            _make_result("License", "expiry", output="2030-01-01"),
        ]
        redacted = _redact_sensitive_outputs(results)
        assert redacted[0]["output"] == _REDACTED
        assert redacted[1]["output"] == "4.3.1"
        assert redacted[2]["output"] == _REDACTED

    def test_original_results_are_not_mutated(self):
        original = [_make_result("License", "key", output="SECRET")]
        _redact_sensitive_outputs(original)
        assert original[0]["output"] == "SECRET"

    def test_original_results_not_mutated_by_pattern_scrub(self):
        original = [_make_result("Database", "status", output=f"key {_SAMPLE_KEY}")]
        _redact_sensitive_outputs(original)
        assert original[0]["output"] == f"key {_SAMPLE_KEY}"

    def test_empty_list(self):
        assert _redact_sensitive_outputs([]) == []

    def test_missing_group_key(self):
        result = {"test": {"name": "license check"}, "output": "key=X", "error": ""}
        redacted = _redact_sensitive_outputs([result])
        assert redacted[0]["output"] == _REDACTED

    def test_missing_test_key(self):
        result = {"group": {"name": "License"}, "output": "key=X", "error": ""}
        redacted = _redact_sensitive_outputs([result])
        assert redacted[0]["output"] == _REDACTED

    @pytest.mark.parametrize(
        "group,test",
        [
            ("", ""),
            ("Runtime", "r_version"),
            ("Database", "postgres"),
        ],
    )
    def test_non_license_checks_pass_through(self, group, test):
        results = [_make_result(group, test, output="some output", error="some error")]
        redacted = _redact_sensitive_outputs(results)
        assert redacted[0]["output"] == "some output"
        assert redacted[0]["error"] == "some error"

    def test_key_in_non_license_check_output_is_scrubbed(self):
        # Defense in depth: a key surfacing in a check whose name does not
        # mention "license" is still scrubbed, without wiping the whole field.
        results = [_make_result("server", "config-dump", output=f"license = {_SAMPLE_KEY}\nok")]
        redacted = _redact_sensitive_outputs(results)
        assert _SAMPLE_KEY not in redacted[0]["output"]
        assert _REDACTED in redacted[0]["output"]
        assert "ok" in redacted[0]["output"]

    def test_key_in_non_license_check_error_is_scrubbed(self):
        results = [_make_result("server", "config-dump", output="", error=f"bad key {_SAMPLE_KEY}")]
        redacted = _redact_sensitive_outputs(results)
        assert _SAMPLE_KEY not in redacted[0]["error"]
        assert _REDACTED in redacted[0]["error"]

    def test_job_key_in_non_license_check_is_scrubbed(self):
        # The rmarkdown-sandbox check echoes the connect-session job key, which
        # is neither a "license" check nor a license-key-shaped token, so it must
        # be scrubbed by its own layer while leaving the surrounding log intact.
        output = f"[connect-session] Job Key: {_SAMPLE_JOB_KEY}\nJob started"
        results = [_make_result("rmarkdown-sandbox", "mounts", output=output)]
        redacted = _redact_sensitive_outputs(results)
        assert _SAMPLE_JOB_KEY not in redacted[0]["output"]
        assert _REDACTED in redacted[0]["output"]
        assert "Job started" in redacted[0]["output"]

    def test_job_key_in_non_license_check_error_is_scrubbed(self):
        error = f"Job Key: {_SAMPLE_JOB_KEY}"
        results = [_make_result("rmarkdown-sandbox", "mounts", output="", error=error)]
        redacted = _redact_sensitive_outputs(results)
        assert _SAMPLE_JOB_KEY not in redacted[0]["error"]
        assert _REDACTED in redacted[0]["error"]

    def test_original_results_not_mutated_by_job_key_scrub(self):
        output = f"Job Key: {_SAMPLE_JOB_KEY}"
        original = [_make_result("rmarkdown-sandbox", "mounts", output=output)]
        _redact_sensitive_outputs(original)
        assert original[0]["output"] == output


class TestScrubLicenseKeys:
    def test_exact_key_is_scrubbed(self):
        assert _scrub_license_keys(_SAMPLE_KEY) == _REDACTED

    def test_key_embedded_in_text_is_scrubbed(self):
        assert _scrub_license_keys(f"Product-Key: {_SAMPLE_KEY} Has-Key: Yes") == (
            f"Product-Key: {_REDACTED} Has-Key: Yes"
        )

    @pytest.mark.parametrize(
        "text",
        [
            "4.3.1",
            "ABC-123",
            "no keys here",
            "AAAA-BBBB-CCCC",  # too few groups
            "",
        ],
    )
    def test_non_key_text_is_left_alone(self, text):
        assert _scrub_license_keys(text) == text

    def test_non_string_values_pass_through(self):
        assert _scrub_license_keys(None) is None
        assert _scrub_license_keys(42) == 42


class TestScrubJobKeys:
    def test_job_key_after_label_is_scrubbed(self):
        line = f"[connect-session] Job Key: {_SAMPLE_JOB_KEY}"
        assert _scrub_job_keys(line) == "[connect-session] Job Key: [redacted]"

    def test_label_is_preserved(self):
        result = _scrub_job_keys(f"Job Key: {_SAMPLE_JOB_KEY}")
        assert result == f"Job Key: {_REDACTED}"
        assert _SAMPLE_JOB_KEY not in result

    def test_multiline_output_only_key_scrubbed(self):
        text = f"line one\n[connect-session] Job Key: {_SAMPLE_JOB_KEY}\nJob started"
        scrubbed = _scrub_job_keys(text)
        assert _SAMPLE_JOB_KEY not in scrubbed
        assert "line one" in scrubbed
        assert "Job started" in scrubbed

    def test_case_insensitive_label_match(self):
        assert _scrub_job_keys(f"job key: {_SAMPLE_JOB_KEY}") == f"job key: {_REDACTED}"

    @pytest.mark.parametrize(
        "text",
        [
            "no job key here",
            "Jobs Key: value",  # not the "Job Key:" label
            "4.3.1",
            "",
        ],
    )
    def test_text_without_job_key_label_is_left_alone(self, text):
        assert _scrub_job_keys(text) == text

    def test_non_string_values_pass_through(self):
        assert _scrub_job_keys(None) is None
        assert _scrub_job_keys(42) == 42
