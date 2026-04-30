"""Tests for vip.app.app module — startup seeding and run-handler behaviour."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from vip.app.app import seed_results_if_missing


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
