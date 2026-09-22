"""Tests for vip.plugin module — unproven/not_applicable skip attestation."""

from __future__ import annotations

import json


class TestPluginIntegration:
    """Integration tests using pytester to exercise the plugin end-to-end.

    pytester runs pytest in a subprocess, so each invocation gets its own
    plugin state (including a fresh ``_results`` list).
    """

    def test_unproven_skip_is_flagged_and_reason_is_clean(self, selftest_pytester):
        """The sentinel is an internal transport detail: it classifies the
        skip and must not leak into the reason a human reads.
        """
        selftest_pytester.makepyfile(
            """
            from vip import attest

            def test_needs_auth():
                attest.unproven("Workbench authentication did not complete")
            """
        )
        report_path = selftest_pytester.path / "results.json"
        selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
        )
        result = json.loads(report_path.read_text())["results"][0]
        assert result["outcome"] == "skipped"
        assert result["unproven"] is True
        assert result["skip_reason"] == "Workbench authentication did not complete"

    def test_not_applicable_skip_is_not_flagged(self, selftest_pytester):
        selftest_pytester.makepyfile(
            """
            from vip import attest

            def test_nothing_to_do():
                attest.not_applicable("Connect is not configured")
            """
        )
        report_path = selftest_pytester.path / "results.json"
        selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
        )
        result = json.loads(report_path.read_text())["results"][0]
        assert result["outcome"] == "skipped"
        assert result["unproven"] is False
        assert result["skip_reason"] == "Connect is not configured"

    def test_plain_pytest_skip_defaults_to_not_unproven(self, selftest_pytester):
        # The 160 untriaged skip sites keep their current meaning until they
        # are converted deliberately; this field must not change under them.
        selftest_pytester.makepyfile(
            """
            import pytest

            def test_plain_skip():
                pytest.skip("some existing reason")
            """
        )
        report_path = selftest_pytester.path / "results.json"
        selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
        )
        result = json.loads(report_path.read_text())["results"][0]
        assert result["unproven"] is False

    def test_unproven_from_a_fixture_is_flagged(self, selftest_pytester):
        """Real unproven skips fire from fixtures (the auth gate), which land
        in the 'setup' phase rather than 'call'.
        """
        selftest_pytester.makepyfile(
            """
            import pytest
            from vip import attest

            @pytest.fixture
            def workbench_session():
                attest.unproven("no usable IdP session")

            def test_uses_session(workbench_session):
                assert True
            """
        )
        report_path = selftest_pytester.path / "results.json"
        selftest_pytester.runpytest(
            "--vip-config=vip.toml",
            f"--vip-report={report_path}",
        )
        result = json.loads(report_path.read_text())["results"][0]
        assert result["outcome"] == "skipped"
        assert result["unproven"] is True
        assert result["skip_reason"] == "no usable IdP session"

    def test_unproven_reason_is_rewritten_for_downstream_reporters(self, selftest_pytester):
        """The sentinel must not reach pytest's own --junitxml.

        CI runs pytest --junitxml directly (ci.yml, connect-smoke.yml,
        packagemanager-smoke.yml), and AGENTS.md tells operators to read skip
        reasons out of that file because VIP's terminal reporter hides them.
        A raw sentinel there is both unreadable and hides the classification,
        so rewrite report.longrepr in place rather than only cleaning up
        VIP's own artifacts.
        """
        selftest_pytester.makepyfile(
            """
            from vip import attest

            def test_needs_auth():
                attest.unproven("Workbench authentication did not complete")
            """
        )
        xml_path = selftest_pytester.path / "native-junit.xml"
        selftest_pytester.runpytest("--vip-config=vip.toml", f"--junitxml={xml_path}")
        raw = xml_path.read_bytes()
        assert b"vip:unproven" not in raw, "internal sentinel leaked to native JUnit"
        assert b"#x00" not in raw, "escaped NUL leaked to native JUnit"
        assert b"UNPROVEN: Workbench authentication did not complete" in raw

    def test_ordinary_skip_reason_is_left_alone_downstream(self, selftest_pytester):
        selftest_pytester.makepyfile(
            """
            from vip import attest

            def test_nothing_to_do():
                attest.not_applicable("Connect is not configured")
            """
        )
        xml_path = selftest_pytester.path / "native-junit.xml"
        selftest_pytester.runpytest("--vip-config=vip.toml", f"--junitxml={xml_path}")
        raw = xml_path.read_bytes()
        assert b"Connect is not configured" in raw
        assert b"UNPROVEN" not in raw

    def test_unproven_summary_names_the_flag_that_actually_works(self, selftest_pytester):
        """The summary is printed by the plugin, so it is reached by a bare
        `pytest` run too -- where the option is spelled --vip-allow-unproven.
        Naming only the `vip verify` alias sends those users to a flag pytest
        rejects.
        """
        selftest_pytester.makepyfile(
            """
            from vip import attest

            def test_needs_auth():
                attest.unproven("auth did not complete")
            """
        )
        result = selftest_pytester.runpytest("--vip-config=vip.toml")
        printed = result.stdout.str() + result.stderr.str()
        assert "--vip-allow-unproven" in printed
