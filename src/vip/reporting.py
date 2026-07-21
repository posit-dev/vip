"""Utilities for generating the VIP Quarto report from test results JSON."""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
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
    concise_error: str | None = None
    markers: list[str] = field(default_factory=list)
    scenario_title: str | None = None
    feature_description: str | None = None
    na_version: bool = False

    @property
    def category(self) -> str:
        """Derive the top-level test category from the nodeid."""
        # nodeid looks like "tests/connect/test_auth.py::test_login"
        parts = self.nodeid.split("/")
        if len(parts) >= 2:
            return parts[1]
        return "unknown"

    @property
    def status(self) -> str:
        """Report status, distinguishing N/A-by-version from ordinary skips.

        Returns ``"na_version"`` when the test was skipped because a
        product's version could not be determined (see
        ``plugin._skip_version_unknown``), otherwise returns ``outcome``
        unchanged. Quarto templates key their styling dicts on this value
        instead of raw ``outcome`` so version gaps render distinctly from
        both passes/failures and ordinary (unconfigured-feature) skips.
        """
        if self.na_version and self.outcome == "skipped":
            return "na_version"
        return self.outcome


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
        # N/A-by-version results are still pytest "skipped" outcomes, so they
        # count toward the top-line skipped total; they get their own
        # section/badge in the report via TestResult.status, but the summary
        # count is not split out separately.
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
            concise_error=r.get("concise_error"),
            markers=r.get("markers", []),
            scenario_title=r.get("scenario_title"),
            feature_description=r.get("feature_description"),
            na_version=r.get("na_version", False),
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


def write_junit_xml(data: ReportData, path: str | Path) -> None:
    """Write test results as a JUnit XML file for CI test reporters."""
    suites = ET.Element(
        "testsuites",
        tests=str(data.total),
        failures=str(data.failed),
        errors="0",
        skipped=str(data.skipped),
    )
    suite = ET.SubElement(
        suites,
        "testsuite",
        name="vip",
        tests=str(data.total),
        failures=str(data.failed),
        errors="0",
        skipped=str(data.skipped),
        time=f"{sum(r.duration for r in data.results):.3f}",
    )
    for r in data.results:
        case = ET.SubElement(
            suite,
            "testcase",
            name=r.scenario_title or r.nodeid,
            classname=r.feature_description or r.category,
            time=f"{r.duration:.3f}",
        )
        if r.outcome == "failed":
            failure = ET.SubElement(
                case,
                "failure",
                message=r.concise_error or r.longrepr or "test failed",
            )
            failure.text = r.longrepr or r.concise_error or ""
        elif r.outcome == "skipped":
            reason = "N/A for this product version" if r.na_version else "skipped"
            ET.SubElement(case, "skipped", message=reason)

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suites).write(p, encoding="utf-8", xml_declaration=True)


def _installed_vip_tests_dir() -> Path | None:
    """Return the directory of the installed ``vip_tests`` package, if any."""
    try:
        import vip_tests
    except Exception:
        return None
    location = getattr(vip_tests, "__file__", None)
    return Path(location).resolve().parent if location else None


def troubleshooting_path() -> Path | None:
    """Locate ``troubleshooting.toml`` in a source checkout or installed package.

    The report templates render from a working ``report/`` directory, so a
    source checkout is found via the repo-relative ``../src/vip_tests`` path.
    When VIP is installed as a wheel that path does not exist, so fall back to
    the copy shipped inside the installed ``vip_tests`` package. Returns
    ``None`` when neither is present (the report then renders without hints).
    """
    repo = Path("../src/vip_tests/troubleshooting.toml")
    if repo.exists():
        return repo
    pkg = _installed_vip_tests_dir()
    if pkg is not None:
        candidate = pkg / "troubleshooting.toml"
        if candidate.exists():
            return candidate
    return None


def feature_file_for_nodeid(nodeid: str) -> Path | None:
    """Resolve the ``.feature`` file for a pytest nodeid.

    Works both from a source checkout (repo-relative paths) and when VIP is
    installed as a wheel (resolving inside the installed ``vip_tests``
    package). Returns ``None`` when no matching feature file exists.
    """
    py_file = nodeid.split("::", 1)[0]
    feature_rel = py_file.rsplit(".", 1)[0] + ".feature"
    candidates = [Path("..") / feature_rel, Path(feature_rel)]
    if "vip_tests/" in feature_rel:
        sub = feature_rel.split("vip_tests/", 1)[1]
        pkg = _installed_vip_tests_dir()
        if pkg is not None:
            candidates.append(pkg / sub)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


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
