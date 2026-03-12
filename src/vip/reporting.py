"""Utilities for generating the VIP Quarto report from test results JSON."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


@dataclass
class TestResult:
    nodeid: str
    outcome: str  # "passed", "failed", "skipped"
    duration: float = 0.0
    longrepr: str | None = None
    markers: list[str] = field(default_factory=list)
    scenario_title: str | None = None
    feature_description: str | None = None

    @property
    def category(self) -> str:
        """Derive the top-level test category from the nodeid."""
        # nodeid looks like "tests/connect/test_auth.py::test_login"
        parts = self.nodeid.split("/")
        if len(parts) >= 2:
            return parts[1]
        return "unknown"


@dataclass
class ProductInfo:
    """Metadata about a single product from the test run."""

    name: str = ""
    enabled: bool = False
    url: str = ""
    version: str | None = None
    configured: bool = False


@dataclass
class ReportData:
    deployment_name: str = "Posit Team"
    generated_at: str = ""
    exit_status: int = 0
    products: list[ProductInfo] = field(default_factory=list)
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

    @property
    def generated_at_display(self) -> str:
        """Human-readable timestamp."""
        if not self.generated_at:
            return "N/A"
        try:
            from datetime import datetime, timezone

            dt = datetime.fromisoformat(self.generated_at)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        except Exception:
            return self.generated_at[:19] if self.generated_at else "N/A"

    def by_category(self) -> dict[str, list[TestResult]]:
        categories: dict[str, list[TestResult]] = {}
        for r in self.results:
            categories.setdefault(r.category, []).append(r)
        return categories

    def configured_products(self) -> list[ProductInfo]:
        return [p for p in self.products if p.configured]


def load_results(path: str | Path) -> ReportData:
    """Load test results from a JSON file written by the VIP plugin."""
    p = Path(path)
    if not p.exists():
        return ReportData()

    raw = json.loads(p.read_text())
    results = [
        TestResult(
            nodeid=r["nodeid"],
            outcome=r["outcome"],
            duration=r.get("duration", 0.0),
            longrepr=r.get("longrepr"),
            markers=r.get("markers", []),
            scenario_title=r.get("scenario_title"),
            feature_description=r.get("feature_description"),
        )
        for r in raw.get("results", [])
    ]

    products = []
    for name, info in raw.get("products", {}).items():
        products.append(
            ProductInfo(
                name=name,
                enabled=info.get("enabled", False),
                url=info.get("url", ""),
                version=info.get("version"),
                configured=info.get("configured", False),
            )
        )

    return ReportData(
        deployment_name=raw.get("deployment_name", "Posit Team"),
        generated_at=raw.get("generated_at", ""),
        exit_status=raw.get("exit_status", 0),
        products=products,
        results=results,
    )


def load_troubleshooting(path: str | Path) -> dict[str, dict]:
    """Load troubleshooting hints from a TOML file.

    Returns a dict keyed by scenario title.  Each value contains
    ``summary``, ``likely_causes``, ``suggested_steps``, and optionally
    ``docs_url``.  Returns an empty dict if the file does not exist or
    cannot be parsed.
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with p.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError:
        return {}
