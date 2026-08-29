"""Utilities for generating the VIP Quarto report from test results JSON."""

from __future__ import annotations

import json
import re
import sys
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


VALID_FORMATS = frozenset({"json", "junit", "sarif"})

# results.json schema version. Bump the minor for additive changes (a new
# field); bump the major for a removal, a rename, or a change in the meaning
# of an existing field. Consumers accept an unknown minor and refuse an
# unknown major. A file with no schema_version at all predates versioning
# and is treated as "pre-1.0".
RESULTS_SCHEMA_VERSION = "1.0"


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
    # Human-readable reason a skipped test was skipped (e.g. "high-concurrency
    # localhost loads are flaky on macOS CI runners"), with pytest's "Skipped: "
    # prefix stripped. Populated by the plugin from ``report.longrepr`` — see
    # ``plugin._extract_skip_reason``. ``None`` for non-skips, and also for a
    # skip whose longrepr doesn't have the expected shape (never crash trying
    # to explain a skip). ``longrepr`` itself is deliberately *not* populated
    # for skips (see the plugin's ``pytest_runtest_logreport``): pytest's
    # stringified longrepr for a skip is a 3-tuple embedding the absolute path
    # of the file that called ``skip()``, which has no business in a report
    # that gets archived/published, and skip_reason already carries the part
    # a reader actually wants.
    skip_reason: str | None = None
    # When this check began and ended, UTC ISO 8601, from pytest's report.start
    # and report.stop. This is the call phase, so it excludes fixture setup
    # (except for a setup-phase skip, where it is the setup start). None for a
    # results.json written before these fields existed.
    started_at: str | None = None
    finished_at: str | None = None

    @property
    def category(self) -> str:
        """Derive the top-level test category from the nodeid.

        A nodeid starts with the pytest path to the test file, so the category
        is the directory holding it: ``vip_tests/connect/test_auth.py::test_x``
        is ``connect``.

        Anchor on the ``vip_tests`` package segment rather than a fixed index.
        The prefix depends on how the suite was collected -- a source checkout
        yields ``src/vip_tests/...`` while an installed wheel yields a
        site-packages path -- so the old fixed ``parts[1]`` returned the
        literal string ``"vip_tests"`` for every result this repo actually
        produces. That collapsed the whole Detailed Results page into one
        section headed "Vip Tests" and labelled every SARIF logical location
        ``vip_tests / <check>``. The ``parts[1]`` fallback is kept for nodeids
        that do not run out of the package at all, such as a custom test
        directory passed via ``--vip-test-dir``.
        """
        parts = self.nodeid.split("::", 1)[0].split("/")
        if "vip_tests" in parts:
            # Scan from the right: the innermost ``vip_tests`` is the package
            # root closest to the category directory, so a collection path that
            # happens to nest one inside another (or inside a folder of the
            # same name) still resolves to the real category.
            idx = len(parts) - 1 - parts[::-1].index("vip_tests") + 1
            # Only a directory counts as a category. A file sitting directly
            # in vip_tests/ (conftest.py, say) has no category of its own.
            if idx < len(parts) - 1:
                return parts[idx]
            return "unknown"
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
    # Provenance: what produced this report, so a customer archiving it as
    # evidence can tell which VIP version ran, how long it took, and whether
    # it was a full or `--basic` run. All default to None/unset rather than a
    # concrete-looking value (e.g. 0.0 or "unknown") so an older results.json
    # written before these fields existed loads as "not recorded" instead of
    # silently claiming a value that was never measured.
    schema_version: str | None = None
    vip_version: str | None = None
    run_duration_seconds: float | None = None
    python_version: str | None = None
    platform: str | None = None
    basic_mode: bool | None = None
    # Host / git / CI attribution; see vip.attribution. None when the run used
    # --vip-no-attribution, or for a results.json predating the field.
    execution: dict | None = None

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

    raw = json.loads(p.read_text(encoding="utf-8"))

    # Guard the type before splitting. This loader's documented contract is to
    # warn and carry on, never to raise: it runs inside the Quarto notebook
    # cells (report/index.qmd, details.qmd, vip-report.qmd) where an exception
    # renders as an unreadable traceback instead of a report. A hand-edited or
    # third-party results.json carrying `"schema_version": 1.0` as a JSON
    # number would otherwise raise AttributeError here.
    schema_version = raw.get("schema_version")
    if schema_version is not None and not isinstance(schema_version, str):
        warnings.warn(
            f"results.json schema_version is {schema_version!r}, not a string; "
            "treating it as unversioned",
            stacklevel=2,
        )
        schema_version = None
    if schema_version:
        theirs = schema_version.split(".", 1)[0]
        ours = RESULTS_SCHEMA_VERSION.split(".", 1)[0]
        if theirs != ours:
            direction = "newer than" if theirs > ours else "older than"
            warnings.warn(
                f"results.json schema version {schema_version} is {direction} this vip "
                f"understands ({RESULTS_SCHEMA_VERSION}); some fields may be missing "
                "or misinterpreted",
                stacklevel=2,
            )

    results = [
        TestResult(
            nodeid=r["nodeid"],
            outcome=r["outcome"],
            duration=r.get("duration") or 0.0,
            longrepr=r.get("longrepr"),
            concise_error=r.get("concise_error"),
            # `or []` as well as the default: an explicit JSON null passes
            # through .get() untouched and would reach every consumer as a
            # None to iterate over.
            markers=r.get("markers") or [],
            scenario_title=r.get("scenario_title"),
            feature_description=r.get("feature_description"),
            na_version=r.get("na_version", False),
            skip_reason=r.get("skip_reason"),
            started_at=r.get("started_at"),
            finished_at=r.get("finished_at"),
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
        schema_version=schema_version,
        vip_version=raw.get("vip_version"),
        run_duration_seconds=raw.get("run_duration_seconds"),
        python_version=raw.get("python_version"),
        platform=raw.get("platform"),
        basic_mode=raw.get("basic_mode"),
        execution=raw.get("execution"),
    )


_XML_INVALID_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_ANSI_CSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _xml_safe(text: str) -> str:
    """Strip ANSI escape sequences and XML-1.0-invalid control chars (keep tab/LF/CR)."""
    return _XML_INVALID_CHARS.sub("", _ANSI_CSI.sub("", text))


def write_junit_xml(data: ReportData, path: str | Path) -> None:
    """Write test results as a JUnit XML file for CI test reporters."""
    # VIP's ReportData has no "error" outcome distinct from "failed"; always 0.
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
            name=_xml_safe(r.scenario_title or r.nodeid),
            classname=_xml_safe(r.feature_description or r.category),
            time=f"{r.duration:.3f}",
        )
        if r.outcome == "failed":
            failure = ET.SubElement(
                case,
                "failure",
                message=_xml_safe(r.concise_error or r.longrepr or "test failed"),
            )
            failure.text = _xml_safe(r.longrepr or r.concise_error or "")
        elif r.outcome == "skipped":
            # skip_reason is the real reason (see TestResult.skip_reason); the
            # na_version wording is a fallback for reports written before that
            # field existed, and "skipped" is the last resort with no reason at all.
            if r.skip_reason:
                reason = r.skip_reason
            elif r.na_version:
                reason = "N/A for this product version"
            else:
                reason = "skipped"
            ET.SubElement(case, "skipped", message=_xml_safe(reason))

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suites).write(p, encoding="utf-8", xml_declaration=True)


_SARIF_LEVEL = {"failed": "error", "passed": "none", "skipped": "note"}


def write_sarif(data: ReportData, path: str | Path) -> None:
    """Write test results as SARIF 2.1.0 for secops / code-scanning ingestion.

    Every check emits a result (fail=error, pass=none, skip=note) to give a
    full audit trail of what was validated, not only failures.
    """
    from vip import __version__

    rules: dict[str, dict] = {}
    results: list[dict] = []
    for r in data.results:
        check = r.scenario_title or r.nodeid.split("::")[-1]
        rules.setdefault(
            r.nodeid,
            {"id": r.nodeid, "name": check, "shortDescription": {"text": check}},
        )
        if r.outcome == "failed":
            text = r.concise_error or r.longrepr or "check failed"
        elif r.outcome == "skipped":
            # Same precedence as write_junit_xml: real reason, then the
            # na_version fallback wording, then a generic message.
            if r.skip_reason:
                text = r.skip_reason
            elif r.na_version:
                text = "N/A for this product version"
            else:
                text = "check skipped"
        else:
            text = check
        results.append(
            {
                "ruleId": r.nodeid,
                "level": _SARIF_LEVEL.get(r.outcome, "none"),
                "message": {"text": text},
                "locations": [{"logicalLocations": [{"name": f"{r.category} / {check}"}]}],
            }
        )

    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "vip",
                        "version": __version__,
                        "informationUri": "https://github.com/posit-dev/vip",
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2) + "\n")


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
