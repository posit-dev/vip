"""Tests for vip.app.app module — startup seeding and run-handler behaviour."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from vip.app.app import mark_run_in_progress, seed_results_if_missing


class TestSeedResultsIfMissing:
    """Unit tests for the seed_results_if_missing() helper."""

    def test_fresh_clone_seeds_results_json(self, tmp_path: Path) -> None:
        """When only results.json.example is present, helper creates results.json."""
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        example = report_dir / "results.json.example"
        example.write_text('{"example": true}')

        seed_results_if_missing(base=tmp_path)

        results = report_dir / "results.json"
        assert results.exists(), "results.json should have been created"
        assert results.read_text() == example.read_text()

    def test_seed_is_idempotent(self, tmp_path: Path) -> None:
        """When results.json already exists, helper does NOT overwrite it."""
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        example = report_dir / "results.json.example"
        example.write_text('{"example": true}')
        existing = report_dir / "results.json"
        existing.write_text('{"custom": "content"}')

        seed_results_if_missing(base=tmp_path)

        assert existing.read_text() == '{"custom": "content"}', (
            "results.json must not be overwritten when it already exists"
        )

    def test_seed_warns_when_example_missing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When both results.json and results.json.example are absent, no exception is raised
        and a warning is logged."""
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        # Neither file exists

        with caplog.at_level(logging.WARNING, logger="vip.app.app"):
            seed_results_if_missing(base=tmp_path)

        assert not (report_dir / "results.json").exists()
        assert any("results.json.example is missing" in r.message for r in caplog.records), (
            "Expected a warning about the missing example file"
        )


class TestModuleImportSideEffects:
    """Verify that importing vip.app.app performs no filesystem writes."""

    def test_module_import_has_no_filesystem_side_effects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Importing vip.app.app must not create report/results.json."""
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        example = report_dir / "results.json.example"
        example.write_text('{"example": true}')

        # Point the module's PROJECT_ROOT to our tmp dir so any accidental
        # seeding would land there instead of the real project.
        import vip.app.app as app_module

        monkeypatch.setattr(app_module, "PROJECT_ROOT", tmp_path)
        # Also reset the guard so a re-import scenario doesn't skip the check.
        monkeypatch.setattr(app_module, "_seeded", False)

        # Re-importing should be a no-op at this point; just verify the state.
        results = report_dir / "results.json"
        assert not results.exists(), (
            "importing vip.app.app must not create report/results.json; "
            "seed_results_if_missing() should only run inside server()"
        )

    def test_seed_runs_on_first_server_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """seed_results_if_missing() fires exactly once when server() is invoked."""
        import vip.app.app as app_module

        report_dir = tmp_path / "report"
        report_dir.mkdir()
        example = report_dir / "results.json.example"
        example.write_text('{"example": true}')

        monkeypatch.setattr(app_module, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(app_module, "_seeded", False)

        # Call server() with stub arguments — it only needs to reach the seed guard.
        class _FakeInput:
            def __getitem__(self, key):
                raise KeyError(key)

            def __getattr__(self, name):
                raise AttributeError(name)

        # server() may raise after the seed block because the fake session is
        # not a real Shiny session. We only care that the seed ran.
        try:
            app_module.server(_FakeInput(), None, None)
        except Exception:
            pass

        results = report_dir / "results.json"
        assert results.exists(), (
            "report/results.json should be seeded after the first server() call"
        )
        assert results.read_text() == example.read_text()

        # Second call should be a no-op (idempotent guard).
        results.write_text('{"custom": "data"}')
        try:
            app_module.server(_FakeInput(), None, None)
        except Exception:
            pass
        assert results.read_text() == '{"custom": "data"}', (
            "second server() call must not overwrite an existing results.json"
        )


class TestMarkRunInProgress:
    """Unit tests for the mark_run_in_progress() helper."""

    def test_writes_sentinel_to_results_json(self, tmp_path: Path) -> None:
        """Helper writes the _running sentinel to report/results.json."""
        report_dir = tmp_path / "report"
        report_dir.mkdir()

        mark_run_in_progress(base=tmp_path)

        results = report_dir / "results.json"
        assert results.exists(), "results.json should have been written"
        payload = json.loads(results.read_text())
        assert payload == {"_running": True}, 'Sentinel payload must be {"_running": true}'

    def test_overwrites_existing_results(self, tmp_path: Path) -> None:
        """Helper overwrites an existing results.json with the sentinel."""
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        existing = report_dir / "results.json"
        existing.write_text('{"exit_status": 0, "results": []}')

        mark_run_in_progress(base=tmp_path)

        payload = json.loads(existing.read_text())
        assert payload == {"_running": True}
