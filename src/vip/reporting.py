"""Utilities for generating the VIP Quarto report from test results JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TestResult:
    nodeid: str
    outcome: str  # "passed", "failed", "skipped"
    duration: float = 0.0
    longrepr: str | None = None
    markers: list[str] = field(default_factory=list)

    @property
    def category(self) -> str:
        """Derive the top-level test category from the nodeid."""
        # nodeid looks like "tests/connect/test_auth.py::test_login"
        parts = self.nodeid.split("/")
        if len(parts) >= 2:
            return parts[1]
        return "unknown"


@dataclass
class ReportData:
    deployment_name: str = "Posit Team"
    generated_at: str = ""
    exit_status: int = 0
    results: list[TestResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.outcome == "passed")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.outcome == "failed")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.outcome == "skipped")

    def by_category(self) -> dict[str, list[TestResult]]:
        categories: dict[str, list[TestResult]] = {}
        for r in self.results:
            categories.setdefault(r.category, []).append(r)
        return categories


def load_results(path: str | Path) -> ReportData:
    """Load test results from a JSON file written by the VIP plugin."""
    raw = json.loads(Path(path).read_text())
    results = [
        TestResult(
            nodeid=r["nodeid"],
            outcome=r["outcome"],
            duration=r.get("duration", 0.0),
            longrepr=r.get("longrepr"),
            markers=r.get("markers", []),
        )
        for r in raw.get("results", [])
    ]
    return ReportData(
        deployment_name=raw.get("deployment_name", "Posit Team"),
        generated_at=raw.get("generated_at", ""),
        exit_status=raw.get("exit_status", 0),
        results=results,
    )
