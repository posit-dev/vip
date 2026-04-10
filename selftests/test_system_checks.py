"""Tests for the license-output redaction helper in test_system_checks."""

from __future__ import annotations

import pytest

from vip_tests.connect.test_system_checks import _REDACTED, _redact_license_outputs


def _make_result(group: str, test: str, output: str = "data", error: str = "") -> dict:
    return {"group": {"name": group}, "test": {"name": test}, "output": output, "error": error}


class TestRedactLicenseOutputs:
    def test_license_group_is_redacted(self):
        results = [_make_result("License", "activation check", output="key=SECRET")]
        redacted = _redact_license_outputs(results)
        assert redacted[0]["output"] == _REDACTED
        assert redacted[0]["error"] == _REDACTED

    def test_license_in_test_name_is_redacted(self):
        results = [_make_result("System", "license validity", output="key=SECRET")]
        redacted = _redact_license_outputs(results)
        assert redacted[0]["output"] == _REDACTED
        assert redacted[0]["error"] == _REDACTED

    def test_non_license_check_is_not_redacted(self):
        results = [_make_result("Database", "connection", output="ok", error="")]
        redacted = _redact_license_outputs(results)
        assert redacted[0]["output"] == "ok"
        assert redacted[0]["error"] == ""

    def test_case_insensitive_group_match(self):
        results = [_make_result("LICENSE", "check", output="secret")]
        redacted = _redact_license_outputs(results)
        assert redacted[0]["output"] == _REDACTED

    def test_case_insensitive_test_name_match(self):
        results = [_make_result("System", "LICENSE_CHECK", output="secret")]
        redacted = _redact_license_outputs(results)
        assert redacted[0]["output"] == _REDACTED

    def test_mixed_results_selective_redaction(self):
        results = [
            _make_result("License", "key", output="ABC-123"),
            _make_result("Runtime", "r_version", output="4.3.1"),
            _make_result("License", "expiry", output="2030-01-01"),
        ]
        redacted = _redact_license_outputs(results)
        assert redacted[0]["output"] == _REDACTED
        assert redacted[1]["output"] == "4.3.1"
        assert redacted[2]["output"] == _REDACTED

    def test_original_results_are_not_mutated(self):
        original = [_make_result("License", "key", output="SECRET")]
        _redact_license_outputs(original)
        assert original[0]["output"] == "SECRET"

    def test_empty_list(self):
        assert _redact_license_outputs([]) == []

    def test_missing_group_key(self):
        result = {"test": {"name": "license check"}, "output": "key=X", "error": ""}
        redacted = _redact_license_outputs([result])
        assert redacted[0]["output"] == _REDACTED

    def test_missing_test_key(self):
        result = {"group": {"name": "License"}, "output": "key=X", "error": ""}
        redacted = _redact_license_outputs([result])
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
        redacted = _redact_license_outputs(results)
        assert redacted[0]["output"] == "some output"
        assert redacted[0]["error"] == "some error"
