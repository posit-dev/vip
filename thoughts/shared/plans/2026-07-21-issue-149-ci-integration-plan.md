# CI Pipeline Integration (#149) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add JUnit XML and SARIF output formats to `vip verify`, a `--ci` convenience flag, and a CLI-based container entrypoint so VIP plugs into customer security-ops / CI pipelines.

**Architecture:** Two pure writer functions in `reporting.py` consume the existing `ReportData` model and emit JUnit/SARIF. `pytest_sessionfinish` re-reads the just-written `results.json` via `load_results()` and emits the requested extra formats as siblings. The `vip verify` CLI grows a comma-separated `--format` option and a `--ci` sugar flag that forwards to a new `--vip-format` pytest option. The Dockerfile entrypoint switches from raw pytest to the `vip` CLI.

**Tech Stack:** Python 3.10+, stdlib `argparse` / `xml.etree.ElementTree` / `json`, pytest plugin API, `uv`, Docker.

## Global Constraints

- Python floor: 3.10 (`from __future__ import annotations` already used throughout; no 3.11+ syntax in `reporting.py` outside the existing `sys.version_info` guard).
- No new runtime dependencies — JUnit via stdlib `xml.etree.ElementTree`, SARIF via stdlib `json`.
- `results.json` + `failures.json` are ALWAYS written regardless of `--format` (Quarto HTML depends on `results.json`). `--format` is additive only.
- `--format` values: `json`, `junit`, `sarif`. Comma-separated. Default `json`. Unknown values are rejected.
- Extra-format files are siblings of `--report`'s directory: `junit.xml`, `results.sarif`.
- SARIF: SARIF 2.1.0; every check emits a result (fail=`error`, pass=`none`, skip=`note`); `logicalLocations` naming `"<category> / <check>"`, no physical source location.
- Conventional-commit messages (`feat:` / `test:` / `docs:` / `chore:`) — enforced by `pr-title.yml`; semantic-release consumes them.
- Do not run the container-dependent smoke suites; use `uv run pytest selftests/` for verification.
- Lint/format gate: `uv run ruff check src/ selftests/` and `uv run ruff format --check src/ selftests/` must pass; `uv run mypy src/` must pass.

---

### Task 1: JUnit XML writer

**Files:**
- Modify: `src/vip/reporting.py` (add `write_junit_xml` after `load_results`, ~line 156)
- Test: `selftests/test_reporting.py` (add `TestWriteJUnitXml` class)

**Interfaces:**
- Consumes: `ReportData`, `TestResult` (existing dataclasses in `reporting.py`).
- Produces: `write_junit_xml(data: ReportData, path: str | Path) -> None` — writes a JUnit XML file. `testcase.name` = `scenario_title or nodeid`; `testcase.classname` = `feature_description or category`; failed → `<failure>` child carrying `concise_error or longrepr`; skipped → `<skipped>` child (message = version-gate note when `na_version`); passed → no child.

- [ ] **Step 1: Write the failing test**

```python
# add to selftests/test_reporting.py
import xml.etree.ElementTree as ET

from vip.reporting import write_junit_xml, write_sarif  # write_sarif added in Task 2


class TestWriteJUnitXml:
    def _sample(self) -> ReportData:
        return ReportData(
            deployment_name="Acme Team",
            generated_at="2026-07-21T12:00:00+00:00",
            results=[
                TestResult(
                    nodeid="tests/connect/test_auth.py::test_login",
                    outcome="passed",
                    duration=1.5,
                    scenario_title="User can log in",
                    feature_description="Connect authentication",
                ),
                TestResult(
                    nodeid="tests/workbench/test_sessions.py::test_start",
                    outcome="failed",
                    duration=0.5,
                    concise_error="test_start: TimeoutError session did not start",
                    scenario_title="Session starts",
                    feature_description="Workbench sessions",
                ),
                TestResult(
                    nodeid="tests/connect/test_api.py::test_v1",
                    outcome="skipped",
                    na_version=True,
                    scenario_title="API v1 available",
                ),
            ],
        )

    def test_writes_well_formed_xml_with_counts(self, tmp_path):
        out = tmp_path / "junit.xml"
        write_junit_xml(self._sample(), out)
        tree = ET.parse(out)
        suite = tree.getroot().find("testsuite")
        assert suite.get("tests") == "3"
        assert suite.get("failures") == "1"
        assert suite.get("skipped") == "1"

    def test_failure_carries_concise_error(self, tmp_path):
        out = tmp_path / "junit.xml"
        write_junit_xml(self._sample(), out)
        tree = ET.parse(out)
        cases = {c.get("name"): c for c in tree.getroot().iter("testcase")}
        failed = cases["Session starts"]
        failure = failed.find("failure")
        assert failure is not None
        assert "TimeoutError" in failure.get("message")
        assert failed.get("classname") == "Workbench sessions"

    def test_skip_uses_nodeid_when_no_scenario(self, tmp_path):
        out = tmp_path / "junit.xml"
        write_junit_xml(self._sample(), out)
        tree = ET.parse(out)
        cases = {c.get("name"): c for c in tree.getroot().iter("testcase")}
        assert cases["API v1 available"].find("skipped") is not None
        # passed case has no failure/skipped child
        assert cases["User can log in"].find("failure") is None
        assert cases["User can log in"].find("skipped") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest selftests/test_reporting.py::TestWriteJUnitXml -v`
Expected: FAIL with `ImportError: cannot import name 'write_junit_xml'` (and `write_sarif`).

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/vip/reporting.py after load_results()
import xml.etree.ElementTree as ET  # add to imports at top of file


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
                message=r.concise_error or "test failed",
            )
            failure.text = r.longrepr or r.concise_error or ""
        elif r.outcome == "skipped":
            reason = "N/A for this product version" if r.na_version else "skipped"
            ET.SubElement(case, "skipped", message=reason)

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suites).write(p, encoding="utf-8", xml_declaration=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest selftests/test_reporting.py::TestWriteJUnitXml -v`
Expected: PASS (3 tests). Note: the `write_sarif` import will still fail until Task 2 — if running this task in isolation, temporarily drop `write_sarif` from the import line, then restore it in Task 2.

- [ ] **Step 5: Commit**

```bash
git add src/vip/reporting.py selftests/test_reporting.py
git commit -m "feat(report): add JUnit XML output writer"
```

---

### Task 2: SARIF writer

**Files:**
- Modify: `src/vip/reporting.py` (add `write_sarif` after `write_junit_xml`)
- Test: `selftests/test_reporting.py` (add `TestWriteSarif` class)

**Interfaces:**
- Consumes: `ReportData`, `TestResult`; `vip.__version__`.
- Produces: `write_sarif(data: ReportData, path: str | Path) -> None` — writes SARIF 2.1.0 JSON. One `result` per check: level `error` (failed) / `none` (passed) / `note` (skipped). `ruleId` = nodeid; `rules[]` deduped by nodeid. `locations[0].logicalLocations[0].name` = `"<category> / <check>"` where check = `scenario_title or test function name`.

- [ ] **Step 1: Write the failing test**

```python
# add to selftests/test_reporting.py
import json


class TestWriteSarif:
    def _sample(self) -> ReportData:
        return ReportData(
            results=[
                TestResult(
                    nodeid="tests/connect/test_auth.py::test_login",
                    outcome="passed",
                    scenario_title="User can log in",
                ),
                TestResult(
                    nodeid="tests/workbench/test_sessions.py::test_start",
                    outcome="failed",
                    concise_error="test_start: session did not start",
                    scenario_title="Session starts",
                ),
                TestResult(
                    nodeid="tests/connect/test_api.py::test_v1",
                    outcome="skipped",
                    na_version=True,
                    scenario_title="API v1 available",
                ),
            ],
        )

    def test_valid_sarif_envelope(self, tmp_path):
        out = tmp_path / "results.sarif"
        write_sarif(self._sample(), out)
        doc = json.loads(out.read_text())
        assert doc["version"] == "2.1.0"
        assert doc["runs"][0]["tool"]["driver"]["name"] == "vip"
        assert len(doc["runs"][0]["results"]) == 3

    def test_level_mapping_per_outcome(self, tmp_path):
        out = tmp_path / "results.sarif"
        write_sarif(self._sample(), out)
        doc = json.loads(out.read_text())
        levels = {r["ruleId"]: r["level"] for r in doc["runs"][0]["results"]}
        assert levels["tests/connect/test_auth.py::test_login"] == "none"
        assert levels["tests/workbench/test_sessions.py::test_start"] == "error"
        assert levels["tests/connect/test_api.py::test_v1"] == "note"

    def test_rules_deduped_and_logical_location(self, tmp_path):
        out = tmp_path / "results.sarif"
        data = self._sample()
        data.results.append(
            TestResult(nodeid="tests/connect/test_auth.py::test_login", outcome="passed")
        )
        write_sarif(data, out)
        doc = json.loads(out.read_text())
        rule_ids = [r["id"] for r in doc["runs"][0]["tool"]["driver"]["rules"]]
        assert rule_ids.count("tests/connect/test_auth.py::test_login") == 1
        failed = next(
            r for r in doc["runs"][0]["results"]
            if r["ruleId"] == "tests/workbench/test_sessions.py::test_start"
        )
        loc = failed["locations"][0]["logicalLocations"][0]["name"]
        assert loc == "workbench / Session starts"
        assert failed["message"]["text"] == "test_start: session did not start"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest selftests/test_reporting.py::TestWriteSarif -v`
Expected: FAIL with `ImportError: cannot import name 'write_sarif'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/vip/reporting.py after write_junit_xml()
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
            text = "N/A for this product version" if r.na_version else "check skipped"
        else:
            text = check
        results.append(
            {
                "ruleId": r.nodeid,
                "level": _SARIF_LEVEL.get(r.outcome, "none"),
                "message": {"text": text},
                "locations": [
                    {"logicalLocations": [{"name": f"{r.category} / {check}"}]}
                ],
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest selftests/test_reporting.py -v`
Expected: PASS (all reporting tests, including Task 1's).

- [ ] **Step 5: Commit**

```bash
git add src/vip/reporting.py selftests/test_reporting.py
git commit -m "feat(report): add SARIF 2.1.0 output writer"
```

---

### Task 3: Plugin wiring — `--vip-format` and session-end emission

**Files:**
- Modify: `src/vip/plugin.py` (add option near line 84; emit formats in `pytest_sessionfinish` near line 1092, after `results.json` write)
- Test: `selftests/test_plugin.py` (add `TestFormatEmission` class)

**Interfaces:**
- Consumes: `write_junit_xml`, `write_sarif`, `load_results` from `vip.reporting`; existing `--vip-report` option and the `results.json` written at `plugin.py:1088`.
- Produces: a `--vip-format` pytest option (default `"json"`); after writing `results.json`, parses the comma list and writes `junit.xml` / `results.sarif` siblings when requested.

- [ ] **Step 1: Write the failing test**

```python
# add to selftests/test_plugin.py — patterned on the existing pytester/plugin tests.
# This test drives the emission helper directly to avoid a full pytest run.
from pathlib import Path

from vip.plugin import _emit_extra_formats


class TestFormatEmission:
    def _write_results(self, tmp_path: Path) -> Path:
        results = tmp_path / "results.json"
        results.write_text(
            '{"deployment_name": "T", "results": ['
            '{"nodeid": "tests/connect/test_a.py::test_x", "outcome": "failed",'
            ' "concise_error": "boom", "scenario_title": "X"}]}'
        )
        return results

    def test_json_only_writes_nothing_extra(self, tmp_path):
        results = self._write_results(tmp_path)
        _emit_extra_formats("json", results)
        assert not (tmp_path / "junit.xml").exists()
        assert not (tmp_path / "results.sarif").exists()

    def test_junit_and_sarif_written_as_siblings(self, tmp_path):
        results = self._write_results(tmp_path)
        _emit_extra_formats("json,junit,sarif", results)
        assert (tmp_path / "junit.xml").exists()
        assert (tmp_path / "results.sarif").exists()

    def test_unknown_format_ignored_gracefully(self, tmp_path):
        results = self._write_results(tmp_path)
        _emit_extra_formats("junit,bogus", results)  # bogus ignored, junit still written
        assert (tmp_path / "junit.xml").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest selftests/test_plugin.py::TestFormatEmission -v`
Expected: FAIL with `ImportError: cannot import name '_emit_extra_formats'`.

- [ ] **Step 3: Write minimal implementation**

Add the option (after the `--vip-report` block ending at `plugin.py:89`):

```python
    group.addoption(
        "--vip-format",
        default="json",
        help="Comma-separated output formats: json,junit,sarif. json (results.json)"
        " is always written; junit/sarif are added as siblings. (default: json)",
    )
```

Add the helper (module-level, near the other `pytest_sessionfinish` helpers):

```python
def _emit_extra_formats(fmt: str, results_path: Path) -> None:
    """Emit JUnit/SARIF siblings of results_path per a comma-separated format list.

    ``results.json`` is always written by the caller; this only adds the extra
    machine-readable formats. Unknown format tokens are ignored.
    """
    from vip.reporting import load_results, write_junit_xml, write_sarif

    formats = {f.strip().lower() for f in fmt.split(",") if f.strip()}
    if not (formats & {"junit", "sarif"}):
        return
    data = load_results(results_path)
    if "junit" in formats:
        write_junit_xml(data, results_path.parent / "junit.xml")
    if "sarif" in formats:
        write_sarif(data, results_path.parent / "results.sarif")
```

Wire it into `pytest_sessionfinish`, immediately after the `results.json` write succeeds (right after `p.write_text(...)` at `plugin.py:1088`, before the `failures.json` block):

```python
    fmt = session.config.getoption("--vip-format", "json")
    try:
        _emit_extra_formats(fmt, p)
    except OSError as exc:
        warnings.warn(f"VIP: could not write extra formats: {exc}", stacklevel=1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest selftests/test_plugin.py::TestFormatEmission -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/vip/plugin.py selftests/test_plugin.py
git commit -m "feat(plugin): emit JUnit/SARIF via --vip-format at session end"
```

---

### Task 4: CLI `--format` and `--ci` flags

**Files:**
- Modify: `src/vip/cli.py` (add args to `verify_parser` near line 1359; forward in `run_verify` near line 471)
- Test: `selftests/test_cli_verify.py` (add tests + extend `_make_args` defaults)

**Interfaces:**
- Consumes: existing `run_verify` command-assembly (`cli.py:456-492`); `args.report`, `args.format`, `args.ci`.
- Produces: `vip verify --format json,junit,sarif` forwards `--vip-format=<validated>`; `vip verify --ci` forces `--vip-format=json,junit,sarif`, `--tb=short`, and non-interactive (no `--interactive-auth`/`--headless-auth`). Unknown `--format` value exits non-zero before launching pytest.

- [ ] **Step 1: Write the failing test**

```python
# add to selftests/test_cli_verify.py; also add to _make_args defaults:
#     "format": "json",
#     "ci": False,

class TestFormatFlag:
    def test_format_forwarded(self):
        cmd = _capture_cmd(_make_args(format="json,junit,sarif"))
        assert "--vip-format=json,junit,sarif" in cmd

    def test_default_format_is_json(self):
        cmd = _capture_cmd(_make_args())
        assert "--vip-format=json" in cmd

    def test_ci_flag_bundles_formats_and_tb_short(self):
        cmd = _capture_cmd(_make_args(ci=True))
        assert "--vip-format=json,junit,sarif" in cmd
        assert "--tb=short" in cmd

    def test_unknown_format_rejected(self):
        with pytest.raises(SystemExit):
            _capture_cmd(_make_args(format="json,bogus"))
```

(Add `import pytest` to the test file if not already present.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest selftests/test_cli_verify.py::TestFormatFlag -v`
Expected: FAIL (`--vip-format` not in cmd / no SystemExit).

- [ ] **Step 3: Write minimal implementation**

Add args to `verify_parser` (after the `--report` block at `cli.py:1359`):

```python
    verify_parser.add_argument(
        "--format",
        default="json",
        help="Comma-separated output formats: json,junit,sarif. json (results.json)"
        " is always written; junit/sarif land beside --report. (default: json)",
    )
    verify_parser.add_argument(
        "--ci",
        action="store_true",
        default=False,
        help="CI preset: emit json,junit,sarif, use concise tracebacks, and run"
        " strictly non-interactively.",
    )
```

Forward in `run_verify` (replace the `if args.report:` block at `cli.py:470-471` region; insert format handling right after it):

```python
    if args.report:
        cmd.append(f"--vip-report={args.report}")

    _VALID_FORMATS = {"json", "junit", "sarif"}
    fmt = "json,junit,sarif" if getattr(args, "ci", False) else getattr(args, "format", "json")
    requested = [f.strip().lower() for f in fmt.split(",") if f.strip()]
    unknown = [f for f in requested if f not in _VALID_FORMATS]
    if unknown:
        print(
            f"Error: unknown --format value(s): {', '.join(unknown)}. "
            f"Valid: {', '.join(sorted(_VALID_FORMATS))}.",
            file=sys.stderr,
        )
        sys.exit(2)
    cmd.append(f"--vip-format={','.join(requested)}")
```

Then apply the `--ci` non-interactive + concise behavior. Add, just before `cmd.extend(args.pytest_args)` at `cli.py:492`:

```python
    if getattr(args, "ci", False):
        cmd.append("--tb=short")
```

`--ci` non-interactivity is inherent: it does not set `interactive_auth`/`headless_auth`, and those default to `False`, so no browser is launched. (No extra code needed; covered by `_check_credentials` fail-fast.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest selftests/test_cli_verify.py -v`
Expected: PASS (existing + new `TestFormatFlag`).

- [ ] **Step 5: Commit**

```bash
git add src/vip/cli.py selftests/test_cli_verify.py
git commit -m "feat(cli): add --format and --ci flags to vip verify"
```

---

### Task 5: Container entrypoint rework

**Files:**
- Modify: `Dockerfile` (ENTRYPOINT/CMD near the end)

**Interfaces:**
- Consumes: the `vip` console-script installed by `uv sync` (`pyproject.toml [project.scripts] vip = "vip.cli:main"`).
- Produces: `docker run <img>` runs `vip verify`; `docker run <img> status --json` (and other subcommands) reachable; `docker run <img> --ci` runs `vip verify --ci`.

- [ ] **Step 1: Change the entrypoint**

Replace the final two lines of `Dockerfile`:

```dockerfile
# Default entrypoint is the vip CLI; default subcommand is verify.
# Config file should be mounted at /app/vip.toml
ENTRYPOINT ["uv", "run", "vip"]

# Default args: run verify. Override to reach other subcommands, e.g.
#   docker run <img> status --json
#   docker run <img> --ci
CMD ["verify"]
```

- [ ] **Step 2: Verify the image builds and the entrypoint resolves**

Run:
```bash
docker build -t vip-ci-test . && \
docker run --rm --entrypoint uv vip-ci-test run vip --help | head -5
```
Expected: build succeeds; help output lists `verify`, `status`, `report` subcommands.

(If Docker is unavailable in the environment, note this step as deferred-to-CI and verify the `Dockerfile` diff by inspection instead — `docker.yml` builds it on the PR.)

- [ ] **Step 3: Commit**

```bash
git add Dockerfile
git commit -m "feat(docker): run the vip CLI as the container entrypoint"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md` (add a "CI / pipeline integration" section)
- Modify: `AGENTS.md` (if it enumerates `vip verify` options, add `--format`/`--ci`)

**Interfaces:**
- Consumes: the flags/behaviors from Tasks 1–5. No code.
- Produces: user-facing docs. `CHANGELOG.md` is NOT hand-edited (semantic-release generates it from the `feat:` commits).

- [ ] **Step 1: Add the README section**

Add a section such as:

````markdown
## CI / pipeline integration

VIP emits machine-readable output for security-ops and CI/CD pipelines.

`vip verify` always writes `report/results.json` (and `report/failures.json` on
failures). Add JUnit XML and/or SARIF with `--format`:

```bash
vip verify --format json,junit,sarif
# report/results.json   (always)
# report/junit.xml       (--format junit)  -> CI test dashboards
# report/results.sarif   (--format sarif)  -> GitHub code scanning / secops
```

The `--ci` preset bundles all three formats with concise output and strict
non-interactive behavior:

```bash
vip verify --ci
```

### Container

An official image is published to `ghcr.io/posit-dev/vip`. The entrypoint is the
`vip` CLI; the default subcommand is `verify`:

```bash
docker run --rm -v "$PWD/vip.toml:/app/vip.toml" ghcr.io/posit-dev/vip --ci
# other subcommands are reachable too:
docker run --rm -v "$PWD/vip.toml:/app/vip.toml" ghcr.io/posit-dev/vip status --json
```
````

- [ ] **Step 2: Update AGENTS.md if it lists verify options**

Run: `grep -n "vip verify\|--report\|--verbose" AGENTS.md`
If a `vip verify` options list exists, add one line each for `--format` and `--ci` mirroring the README wording. If no such list exists, skip (no change).

- [ ] **Step 3: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs: document --format, --ci, and the container entrypoint"
```

---

### Task 7: Full verification sweep

**Files:** none (verification only)

- [ ] **Step 1: Lint, format, types**

Run:
```bash
uv run ruff check src/ selftests/ && \
uv run ruff format --check src/ selftests/ && \
uv run mypy src/
```
Expected: all pass.

- [ ] **Step 2: Full selftest suite**

Run: `uv run pytest selftests/ -q`
Expected: all pass (baseline was 228 passed for the touched files; total suite green).

- [ ] **Step 3: End-to-end smoke of the writers via the CLI path**

Run:
```bash
uv run python -c "
from pathlib import Path
from vip.reporting import ReportData, TestResult, write_junit_xml, write_sarif
d = ReportData(results=[TestResult(nodeid='tests/connect/t.py::a', outcome='failed', concise_error='x', scenario_title='A')])
write_junit_xml(d, '/tmp/j.xml'); write_sarif(d, '/tmp/r.sarif')
import xml.etree.ElementTree as ET, json
ET.parse('/tmp/j.xml'); json.loads(Path('/tmp/r.sarif').read_text())
print('OK: junit + sarif well-formed')
"
```
Expected: `OK: junit + sarif well-formed`.

- [ ] **Step 4: No commit** (verification task; fixes, if any, fold into the relevant task's commit)

---

## Self-Review

**Spec coverage:**
- JUnit XML → Task 1. ✅
- SARIF (all-outcomes, logical locations) → Task 2. ✅
- Plugin wiring / `--vip-format` / siblings-in-report-dir / json-always-on → Task 3. ✅
- CLI `--format` (comma-separated, validated) + `--ci` → Task 4. ✅
- Container entrypoint rework → Task 5. ✅
- Docs (README + AGENTS) → Task 6; CHANGELOG via semantic-release. ✅
- Testing (TDD each writer + CLI) → Tasks 1–4 + sweep in Task 7. ✅

**Type consistency:** `write_junit_xml(data, path)` / `write_sarif(data, path)` signatures match across reporting.py, plugin `_emit_extra_formats`, and tests. `--vip-format` (plugin) ↔ `--format`/`args.format`/`args.ci` (CLI) forwarding is consistent. `load_results(path)` reused for the dict→dataclass mapping (DRY).

**Placeholder scan:** none — every code step is complete.

**Out of scope (deferred):** per-format path override flags; multi-arch images; promoting VIP's own smoke workflows (#409).
