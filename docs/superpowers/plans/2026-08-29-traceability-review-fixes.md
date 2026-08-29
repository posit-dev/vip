# Traceability Review Fixes Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

Goal: Fix eight verified defects in the `feat/part11-traceability` branch so VIP stops refusing untampered evidence and stops rendering a failed control as green.

Architecture: Four independent groups. Sidecar matching gains an exact-then-basename key. The matrix model gains a `failing` fact alongside the existing `executed` fact, which the display layer flattens into a new red badge. The two report backends are brought back into visual and behavioural parity. One cosmetic comparison bug is closed.

Tech Stack: Python 3.10+, pytest, pytest-bdd, httpx, Quarto/Typst. All commands run through `uv run`. Ruff 0.15.0 is the pinned linter and formatter.

Spec: `docs/superpowers/specs/2026-08-29-traceability-review-fixes-design.md`

## Global Constraints

- Run every command through `uv run`. Never bare `python` or `pip`.
- Ruff rules `E`, `F`, `I`, `UP`. Line length 100. Check and format
  `src/ src/vip_tests/ selftests/ examples/`. CI pins ruff to 0.15.0.
- Never run selftests with `-p no:randomly`. CI runs them randomized.
- `ControlEntry.coverage` keeps exactly three values: `covered`, `gap`,
  `not_automatable`. No task adds a fourth.
- `MATRIX_SCHEMA_VERSION` stays `"1.0"`.
- Every dynamic value reaching `src/vip/report_typst.py` passes through `_lit`.
- Visual changes land in `report_content.py` and `report/styles.css` in the same
  commit, so the HTML and PDF editions stay identical.
- Commit after every task. PR-title-style conventional commit messages.
- Never use bold (`**`) when writing markdown files in this repo.

---

### Task 1: Accept a path-qualified checksum sidecar

Files:
- Modify: `src/vip/traceability.py:490` (`verify_results_checksum`)
- Test: `selftests/test_results_checksum.py` (class `TestSidecarParsing`)

Interfaces:
- Consumes: nothing from earlier tasks.
- Produces: `vip.traceability.sidecar_basename(name: str) -> str`, used by Task 2.

- [ ] Step 1: Write the failing tests

Add to `class TestSidecarParsing` in `selftests/test_results_checksum.py`:

```python
    def test_path_qualified_sidecar_verifies(self, tmp_path):
        """`shasum -a 256 report/results.json` from a parent directory."""
        p, digest = self._results(tmp_path)
        p.with_name("results.json.sha256").write_text(f"{digest}  report/results.json\n")
        assert verify_results_checksum(p) == (digest, True)

    def test_windows_path_qualified_sidecar_verifies(self, tmp_path):
        p, digest = self._results(tmp_path)
        p.with_name("results.json.sha256").write_text(f"{digest}  report\\results.json\n")
        assert verify_results_checksum(p) == (digest, True)

    def test_exact_match_still_wins_over_a_basename_collision(self, tmp_path):
        """A sidecar naming this file exactly never reaches the fallback."""
        p, digest = self._results(tmp_path)
        p.with_name("results.json.sha256").write_text(
            f"{'0' * 64}  archive/results.json\n{digest}  results.json\n"
        )
        assert verify_results_checksum(p) == (digest, True)
```

- [ ] Step 2: Run the tests to verify they fail

Run: `uv run pytest selftests/test_results_checksum.py::TestSidecarParsing -v`
Expected: the first two FAIL with `ResultsIntegrityError: ... does not record an entry for results.json`. The third PASSES already.

- [ ] Step 3: Add the basename helper

Add near `_parse_sidecar` in `src/vip/traceability.py`:

```python
def sidecar_basename(name: str) -> str:
    """The bare filename from a sidecar's recorded name.

    Backslashes are normalized first: shasum under Git Bash or MSYS can record
    a Windows-style path, and PurePosixPath would treat the whole thing as one
    filename.
    """
    return PurePosixPath(name.replace("\\", "/")).name
```

Add `PurePosixPath` to the existing `from pathlib import Path` line:

```python
from pathlib import Path, PurePosixPath
```

- [ ] Step 4: Add the fallback to the match

In `verify_results_checksum`, immediately after the existing
`named = [d for d, name in entries if name == p.name]` line and before the
existing `if not named:` block, insert:

```python
    if not named:
        # Fall back to comparing basenames. `shasum -a 256 report/results.json`
        # run from a directory above the file records the path it was given
        # rather than the bare name, and refusing that sidecar reads to an
        # operator as a tamper alarm on a file nobody touched. Exact match
        # stays the primary key, so a multi-file sidecar that already names
        # this file exactly never reaches here and keeps its strict behaviour.
        named = [d for d, name in entries if name and sidecar_basename(name) == p.name]
```

- [ ] Step 5: Run the tests to verify they pass

Run: `uv run pytest selftests/test_results_checksum.py -v`
Expected: PASS, including every pre-existing test in the file.

- [ ] Step 6: Reproduce the original failure end to end

Run:

```bash
cd "$(mktemp -d)" && mkdir report
printf '{"schema_version": "1.0", "results": []}' > report/results.json
shasum -a 256 report/results.json > report/results.json.sha256
uv run --project "$OLDPWD" vip trace --results report/results.json \
  --controls "$OLDPWD/examples/21CFR_part11_validation/controls.toml" --format json > /dev/null
echo "exit=$?"
```

Expected: `exit=0`. Before this task it printed a `does not record an entry` error and exited 1.

- [ ] Step 7: Lint and commit

```bash
uvx ruff@0.15.0 check src/ src/vip_tests/ selftests/ examples/
uvx ruff@0.15.0 format src/ src/vip_tests/ selftests/ examples/
git add src/vip/traceability.py selftests/test_results_checksum.py
git commit -m "fix(traceability): accept a sidecar that records a path, not a bare name"
```

---

### Task 2: Stop the rehomed sidecar manufacturing false alarms

Files:
- Modify: `src/vip/cli.py:1645` (`_rehome_sidecar`)
- Modify: `src/vip/cli.py:780` (the `except OSError` at the call site)
- Test: `selftests/test_results_checksum.py` (the rehome test class)

Interfaces:
- Consumes: `vip.traceability.sidecar_basename` from Task 1.
- Produces: nothing later tasks rely on.

- [ ] Step 1: Write the failing tests

Add to the rehome test class in `selftests/test_results_checksum.py` (the one
whose docstring begins "`vip report --results` copies a results file"):

```python
    def test_path_qualified_source_line_is_rehomed(self, tmp_path):
        """A recorded path must be rewritten, not copied through verbatim."""
        src = tmp_path / "results.json"
        src.write_text('{"results": []}', encoding="utf-8")
        digest = hashlib.sha256(src.read_bytes()).hexdigest()
        self._sidecar_for(src).write_text(f"{digest}  report/results.json\n", encoding="utf-8")

        dest = tmp_path / "out" / "results.json"
        dest.parent.mkdir()
        shutil.copy2(src, dest)
        _rehome_sidecar(self._sidecar_for(src), self._sidecar_for(dest), src.name, dest.name)

        assert self._sidecar_for(dest).read_text().split()[1] == "results.json"
        assert verify_results_checksum(dest) == (digest, True)

    def test_whitespace_only_source_removes_the_destination(self, tmp_path):
        """An empty sidecar is the truncated-upload case; do not manufacture one."""
        src = tmp_path / "results.json"
        src.write_text('{"results": []}', encoding="utf-8")
        self._sidecar_for(src).write_text("   \n\n", encoding="utf-8")

        dest = tmp_path / "out" / "results.json"
        dest.parent.mkdir()
        shutil.copy2(src, dest)
        self._sidecar_for(dest).write_text(f"{'0' * 64}  results.json\n", encoding="utf-8")
        _rehome_sidecar(self._sidecar_for(src), self._sidecar_for(dest), src.name, dest.name)

        assert not self._sidecar_for(dest).exists()
        _, present = verify_results_checksum(dest)
        assert present is False

    def test_undecodable_source_raises_unicode_error_for_the_caller(self, tmp_path):
        """The call site catches this; it must not escape as a bare traceback."""
        src = tmp_path / "results.json"
        src.write_text('{"results": []}', encoding="utf-8")
        self._sidecar_for(src).write_bytes(b"\xff\xfe\x00\x00 not utf-8")

        dest = tmp_path / "out" / "results.json"
        dest.parent.mkdir()
        with pytest.raises(UnicodeDecodeError):
            _rehome_sidecar(self._sidecar_for(src), self._sidecar_for(dest), src.name, dest.name)
```

- [ ] Step 2: Run the tests to verify they fail

Run: `uv run pytest selftests/test_results_checksum.py -v -k "rehomed or whitespace_only or undecodable"`
Expected: the first two FAIL. The third PASSES already (the raise happens, it is
just uncaught at the call site, which Step 5 fixes).

- [ ] Step 3: Rewrite the body of `_rehome_sidecar`

Replace everything in `src/vip/cli.py` from `if not src.is_file():` through the
final `dest.write_text(...)` line of `_rehome_sidecar` with:

```python
    if not src.is_file():
        dest.unlink(missing_ok=True)
        return
    lines = []
    for line in src.read_text(encoding="utf-8-sig").splitlines():
        parts = line.split(None, 1)
        if not parts:
            continue
        recorded = parts[1].strip().lstrip("*") if len(parts) > 1 else None
        # Compare basenames, not the raw recorded name. A sidecar generated
        # from a parent directory records a path, and copying that line
        # through verbatim produces a rehomed sidecar that then fails
        # verification at the destination -- the false tamper alarm this
        # function exists to prevent.
        if recorded is None or sidecar_basename(recorded) == sidecar_basename(src_name):
            lines.append(f"{parts[0]}  {dest_name}")
        else:
            lines.append(line)
    if not lines:
        # A source that parses to zero entries (whitespace-only, truncated)
        # would otherwise produce an empty destination sidecar, which
        # verify_results_checksum refuses as the truncated-upload case. No
        # sidecar is the documented benign state, so produce that instead.
        dest.unlink(missing_ok=True)
        return
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

- [ ] Step 4: Add the import

`_rehome_sidecar` is module-level in `cli.py`. Add the import inside the
function body, at its top, matching this module's existing lazy-import style:

```python
    from vip.traceability import sidecar_basename
```

- [ ] Step 5: Widen the call site's exception handling

At `src/vip/cli.py:780`, change:

```python
        except OSError as exc:
```

to:

```python
        # UnicodeDecodeError as well as OSError: _rehome_sidecar reads with
        # encoding="utf-8-sig" and a corrupt sidecar would otherwise reach the
        # user as a traceback. verify_results_checksum already catches both on
        # the identical read, and the two paths should agree.
        except (OSError, UnicodeDecodeError) as exc:
```

- [ ] Step 6: Run the tests to verify they pass

Run: `uv run pytest selftests/test_results_checksum.py -v`
Expected: PASS, all tests in the file.

- [ ] Step 7: Lint and commit

```bash
uvx ruff@0.15.0 check src/ src/vip_tests/ selftests/ examples/
uvx ruff@0.15.0 format src/ src/vip_tests/ selftests/ examples/
git add src/vip/cli.py selftests/test_results_checksum.py
git commit -m "fix(cli): stop a rehomed sidecar raising a false tamper alarm"
```

---

### Task 3: Separate "a scenario ran" from "a scenario passed"

Files:
- Modify: `src/vip/traceability.py` (`ControlEntry`, `TraceabilityMatrix`)
- Test: `selftests/test_traceability_matrix.py`

Interfaces:
- Consumes: nothing from earlier tasks.
- Produces: `ControlEntry.failing -> bool` and
  `TraceabilityMatrix.covered_with_failure -> list[str]`, used by Tasks 4 and 5.

- [ ] Step 1: Add the shared matrix helper

Tasks 3, 5, 6 and 7 all need to build a matrix from a list of scenario statuses.
Add this once to `selftests/conftest.py`, as a plain module-level function (not
a fixture), so every test file can import it:

```python
def matrix_from_statuses(statuses: dict[str, list[str]]):
    """Build a TraceabilityMatrix from {control_id: [scenario status, ...]}.

    One TestResult per status, tagged `control-<id>`. A status of "na_version"
    is written as a version-gated skip, which is how the plugin records it.
    """
    from vip.reporting import ReportData, TestResult
    from vip.traceability import ControlSpec, build_traceability_matrix

    results = []
    for control_id, control_statuses in statuses.items():
        for i, status in enumerate(control_statuses):
            results.append(
                TestResult(
                    nodeid=f"test_{control_id}.py::test_{i}",
                    outcome="skipped" if status == "na_version" else status,
                    na_version=status == "na_version",
                    markers=[f"control-{control_id}"],
                )
            )
    controls = {
        cid: ControlSpec(control_id=cid, description=f"control {cid}", verification="automated")
        for cid in statuses
    }
    return build_traceability_matrix(ReportData(results=results), controls)
```

Verify it works before writing assertions against it:

Run: `uv run python -c "import sys; sys.path.insert(0, 'selftests'); from conftest import matrix_from_statuses; m = matrix_from_statuses({'c1': ['passed']}); print(m.entries[0].coverage, m.entries[0].executed)"`
Expected: `covered True`

- [ ] Step 3: Write the failing tests

Add to `selftests/test_traceability_matrix.py`, importing the helper with
`from conftest import matrix_from_statuses`. The assertions:

```python
class TestFailingControls:
    """A control whose scenarios ran and did not pass is not evidence."""

    def test_a_failed_scenario_marks_the_control_failing(self):
        matrix = matrix_from_statuses(statuses={"c1": ["failed"]})
        entry = matrix.entries[0]
        assert entry.coverage == "covered"
        assert entry.executed is True
        assert entry.failing is True
        assert matrix.covered_with_failure == ["c1"]

    def test_an_errored_scenario_marks_the_control_failing(self):
        """`error` is a reachable outcome; enumerating only "failed" would miss it."""
        matrix = matrix_from_statuses(statuses={"c1": ["error"]})
        assert matrix.entries[0].failing is True

    def test_a_mixed_pass_and_failure_marks_the_control_failing(self):
        matrix = matrix_from_statuses(statuses={"c1": ["passed", "failed"]})
        assert matrix.entries[0].failing is True
        assert matrix.covered_with_failure == ["c1"]

    def test_a_pass_beside_a_skip_is_not_failing(self):
        matrix = matrix_from_statuses(statuses={"c1": ["passed", "skipped"]})
        assert matrix.entries[0].failing is False
        assert matrix.covered_with_failure == []

    def test_an_all_skipped_control_is_not_failing(self):
        """Not executed and not failing are different states."""
        matrix = matrix_from_statuses(statuses={"c1": ["skipped"]})
        entry = matrix.entries[0]
        assert entry.executed is False
        assert entry.failing is False

    def test_a_version_gated_control_is_not_failing(self):
        matrix = matrix_from_statuses(statuses={"c1": ["na_version"]})
        assert matrix.entries[0].failing is False
```


- [ ] Step 3: Run the tests to verify they fail

Run: `uv run pytest selftests/test_traceability_matrix.py::TestFailingControls -v`
Expected: FAIL with `AttributeError: 'ControlEntry' object has no attribute 'failing'`.

- [ ] Step 4: Add the `failing` property

In `src/vip/traceability.py`, immediately after `ControlEntry.executed`:

```python
    @property
    def failing(self) -> bool:
        """Whether any tagged scenario produced a result that was not a pass.

        The third fact about a control, after "a scenario is tagged"
        (``coverage``) and "a scenario ran" (``executed``). Without it a
        control whose only scenario failed reports as covered and executed,
        which is true and reads as evidence.

        Defined by exclusion rather than by enumerating failure statuses:
        ``error`` is a reachable outcome alongside ``failed``, and an
        enumerated list would let an errored control read as evidenced.
        Non-executing statuses are excluded via ``NON_EXECUTING_STATUSES``, so
        a skip alongside a pass never counts against a control.
        """
        return any(
            m.status not in NON_EXECUTING_STATUSES and m.status != "passed" for m in self.matches
        )
```

- [ ] Step 5: Add the matrix-level list

In `TraceabilityMatrix`, immediately after `covered_without_execution`:

```python
    @property
    def covered_with_failure(self) -> list[str]:
        """Control ids that are covered but whose scenarios did not all pass.

        The mirror of ``covered_without_execution``. That one catches a matrix
        that is green because nothing ran; this one catches a matrix that is
        green because a run that did happen was not a success. Any failing
        scenario qualifies the control, not only an all-failed one: a green
        badge above a visible failing scenario row is the misreading this
        exists to prevent.
        """
        return [
            e.control.control_id for e in self.entries if e.coverage == "covered" and e.failing
        ]
```

- [ ] Step 6: Run the tests to verify they pass

Run: `uv run pytest selftests/test_traceability_matrix.py -v`
Expected: PASS.

- [ ] Step 7: Lint and commit

```bash
uvx ruff@0.15.0 check src/ src/vip_tests/ selftests/ examples/
uvx ruff@0.15.0 format src/ src/vip_tests/ selftests/ examples/
git add src/vip/traceability.py selftests/test_traceability_matrix.py
git commit -m "feat(traceability): record whether a covered control's scenarios passed"
```

---

### Task 4: Render a failed control red, not green

Files:
- Modify: `src/vip/report_content.py:407` (`COVERAGE_STYLE_KEY`, `COVERAGE_LABELS`,
  `display_coverage`, `traceability_summary_rows`)
- Test: `selftests/test_report_content.py`

Interfaces:
- Consumes: `ControlEntry.failing` from Task 3.
- Produces: the display value `"covered_failed"` and its entries in
  `COVERAGE_STYLE_KEY` and `COVERAGE_LABELS`, used by Task 6.

- [ ] Step 1: Write the failing tests

Add to `selftests/test_report_content.py`:

```python
class TestFailedControlDisplay:
    def test_a_failing_control_displays_as_covered_failed(self):
        entry = SimpleNamespace(coverage="covered", executed=True, failing=True)
        assert report_content.display_coverage(entry) == "covered_failed"

    def test_a_failing_control_uses_the_failed_style(self):
        """Reuses the outcome palette so the styles.css drift guard still holds."""
        assert report_content.COVERAGE_STYLE_KEY["covered_failed"] == "failed"

    def test_a_failing_control_is_labelled_failed(self):
        assert report_content.COVERAGE_LABELS["covered_failed"] == "FAILED"

    def test_a_passing_control_still_displays_as_covered(self):
        entry = SimpleNamespace(coverage="covered", executed=True, failing=False)
        assert report_content.display_coverage(entry) == "covered"

    def test_an_all_skipped_control_still_displays_as_not_executed(self):
        entry = SimpleNamespace(coverage="covered", executed=False, failing=False)
        assert report_content.display_coverage(entry) == "covered_not_executed"

    def test_a_gap_is_unaffected(self):
        entry = SimpleNamespace(coverage="gap", executed=False, failing=False)
        assert report_content.display_coverage(entry) == "gap"

    def test_every_coverage_value_has_a_style_and_a_label(self):
        assert set(report_content.COVERAGE_STYLE_KEY) == set(report_content.COVERAGE_LABELS)
```

Import `from types import SimpleNamespace` at the top of the file if it is not
already imported.

- [ ] Step 2: Run the tests to verify they fail

Run: `uv run pytest selftests/test_report_content.py::TestFailedControlDisplay -v`
Expected: FAIL with `KeyError: 'covered_failed'`.

- [ ] Step 3: Add the style and label entries

In `src/vip/report_content.py`, replace the two dicts with:

```python
COVERAGE_STYLE_KEY = {
    "covered": "passed",
    "covered_not_executed": "na_version",
    "covered_failed": "failed",
    "gap": "failed",
    "not_automatable": "skipped",
}

COVERAGE_LABELS = {
    "covered": "COVERED",
    "covered_not_executed": "NOT RUN",
    "covered_failed": "FAILED",
    "gap": "GAP",
    "not_automatable": "N/A (manual)",
}
```

Extend the comment above `COVERAGE_STYLE_KEY` with a final sentence:

```
# and a covered control whose scenarios ran without passing like a failure --
# the same red as a gap, because both mean the control is not evidenced.
```

- [ ] Step 4: Add the branch to `display_coverage`

Replace the body of `display_coverage`:

```python
def display_coverage(entry) -> str:  # noqa: ANN001 - vip.traceability.ControlEntry
    """Flatten coverage, execution and outcome into the one value the report shows."""
    if entry.coverage == "covered" and entry.failing:
        return "covered_failed"
    if entry.coverage == "covered" and not entry.executed:
        return "covered_not_executed"
    return entry.coverage
```

The two new branches cannot both apply: `failing` is false whenever nothing
executed.

- [ ] Step 5: Add the summary row

In `traceability_summary_rows`, insert one row between "Covered, not executed"
and "Gaps":

```python
        ("Covered, failing", str(counts.get("covered_failed", 0))),
```

- [ ] Step 6: Extend the caveat

`TRACEABILITY_CAVEAT` currently says a control shown as NOT RUN skipped itself.
Append one sentence before the final two sentences:

```
"A control shown as FAILED has a tagged scenario that ran and did not pass, "
"so the control is not evidenced by this run. "
```

- [ ] Step 7: Run the tests to verify they pass

Run: `uv run pytest selftests/test_report_content.py -v`
Expected: PASS, including the pre-existing styles.css color drift guard.

- [ ] Step 8: Lint and commit

```bash
uvx ruff@0.15.0 check src/ src/vip_tests/ selftests/ examples/
uvx ruff@0.15.0 format src/ src/vip_tests/ selftests/ examples/
git add src/vip/report_content.py selftests/test_report_content.py
git commit -m "fix(report): render a control whose scenarios failed as failed"
```

---

### Task 5: Warn about failing controls in `vip trace` and the report

Files:
- Modify: `src/vip/report_content.py:500` (`traceability_warning` becomes
  `traceability_warnings`)
- Modify: `src/vip/report_html.py:437` and `src/vip/report_typst.py:566`
  (both call sites)
- Modify: `src/vip/traceability.py:407` (`render_json` summary block)
- Modify: `src/vip/cli.py:1774` (`run_trace` warnings and the closing line)
- Test: `selftests/test_report_content.py`, `selftests/test_traceability_render.py`,
  `selftests/test_trace_cli.py`

Interfaces:
- Consumes: `TraceabilityMatrix.covered_with_failure` from Task 3.
- Produces: `report_content.traceability_warnings(matrix) -> list[str]`,
  replacing the singular `traceability_warning`. Task 6 does not use it, but
  both report backends now iterate the list.

- [ ] Step 1: Write the failing tests

In `selftests/test_report_content.py`:

```python
class TestTraceabilityWarnings:
    def test_a_failing_control_produces_a_warning(self):
        matrix = SimpleNamespace(covered_without_execution=[], covered_with_failure=["c1"])
        warnings_out = report_content.traceability_warnings(matrix)
        assert any("did not pass" in w and "c1" in w for w in warnings_out)

    def test_both_conditions_produce_two_warnings(self):
        matrix = SimpleNamespace(covered_without_execution=["c2"], covered_with_failure=["c1"])
        assert len(report_content.traceability_warnings(matrix)) == 2

    def test_a_clean_matrix_produces_none(self):
        matrix = SimpleNamespace(covered_without_execution=[], covered_with_failure=[])
        assert report_content.traceability_warnings(matrix) == []
```

In `selftests/test_traceability_render.py`, add a test asserting the JSON
summary carries the new key:

```python
def test_json_summary_counts_failing_controls():
    matrix = matrix_from_statuses(statuses={"c1": ["failed"], "c2": ["passed"]})
    summary = json.loads(render_json(matrix))["summary"]
    assert summary["covered_failed"] == 1
    assert summary["covered_and_executed"] == 2
```

Import the helper with `from conftest import matrix_from_statuses` (added in
Task 3).

In `selftests/test_trace_cli.py`, following whatever pattern that file uses to
invoke `run_trace` and capture stderr:

```python
def test_trace_warns_when_a_covered_control_failed(tmp_path, capsys):
    """The mirror of the covered-not-executed warning."""
    results = tmp_path / "results.json"
    results.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "results": [
                    {
                        "nodeid": "t.py::test_a",
                        "outcome": "failed",
                        "markers": ["control-c1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    controls = tmp_path / "controls.toml"
    controls.write_text(
        '[controls.c1]\ndescription = "a control"\nverification = "automated"\n',
        encoding="utf-8",
    )
    run_trace(
        argparse.Namespace(
            results=str(results), controls=str(controls), format="json", output=None
        )
    )
    captured = capsys.readouterr()
    assert "did not pass" in captured.err
    assert "c1" in captured.err
```

Match the `argparse.Namespace` fields to whatever `run_trace` actually reads in
this branch's `src/vip/cli.py`; add any attribute it accesses that is missing
here rather than guessing a default.

- [ ] Step 2: Run the tests to verify they fail

Run: `uv run pytest selftests/test_report_content.py::TestTraceabilityWarnings selftests/test_traceability_render.py selftests/test_trace_cli.py -v`
Expected: FAIL with `AttributeError: module 'vip.report_content' has no attribute 'traceability_warnings'` and `KeyError: 'covered_failed'`.

- [ ] Step 3: Replace `traceability_warning` with the plural form

In `src/vip/report_content.py`, replace the whole function:

```python
def traceability_warnings(matrix) -> list[str]:  # noqa: ANN001
    """Lines naming controls that look covered but are not evidence.

    Two independent conditions, so two lines rather than one combined
    sentence: a control can be counted as covered because nothing ran, or
    because what ran did not pass, and a reader needs to know which.
    """
    lines = []
    failing = matrix.covered_with_failure
    if failing:
        lines.append(
            f"{pluralize(len(failing), 'control')} counted as covered but had a "
            f"scenario that did not pass: {', '.join(failing)}."
        )
    unexecuted = matrix.covered_without_execution
    if unexecuted:
        lines.append(
            f"{pluralize(len(unexecuted), 'control')} counted as covered but had no "
            f"scenario that ran: {', '.join(unexecuted)}."
        )
    return lines
```

- [ ] Step 4: Update both backends to iterate

In `src/vip/report_html.py`, replace:

```python
    warning = traceability_warning(matrix)
    if warning:
        parts.append(f"<p class='trace-warning'><strong>{_esc(warning)}</strong></p>")
```

with:

```python
    for warning in traceability_warnings(matrix):
        parts.append(f"<p class='trace-warning'><strong>{_esc(warning)}</strong></p>")
```

In `src/vip/report_typst.py`, replace:

```python
    warning = traceability_warning(matrix)
    if warning:
        parts.append(_paragraph(warning))
```

with:

```python
    for warning in traceability_warnings(matrix):
        parts.append(_paragraph(warning))
```

Update the `traceability_warning` import to `traceability_warnings` in both
files (`src/vip/report_html.py:32` and `src/vip/report_typst.py:48` name the
import block).

- [ ] Step 5: Add the JSON summary key

In `src/vip/traceability.py`'s `render_json` summary dict, after
`"covered_not_executed"`:

```python
            # Covered and executed, but not a success. The third way a green
            # matrix can mislead, after "nothing is tagged" and "nothing ran".
            "covered_failed": len(matrix.covered_with_failure),
```

`MATRIX_SCHEMA_VERSION` stays `"1.0"`: the key is additive and the `coverage`
field's value set is unchanged.

- [ ] Step 6: Add the CLI warning

In `src/vip/cli.py`'s `run_trace`, immediately before the existing
`unexecuted = matrix.covered_without_execution` block:

```python
    # A covered control whose scenarios ran and failed also counts toward
    # "0 gaps". Coverage records that a scenario ran, not that it passed, and
    # a compliance matrix that stays silent here is the more expensive of the
    # two ways this tool can mislead.
    failing = matrix.covered_with_failure
    if failing:
        print(
            f"Warning: {len(failing)} covered control(s) had a scenario that did not "
            f"pass: {', '.join(failing)}. Coverage records that a scenario ran, not "
            "that it passed.",
            file=sys.stderr,
        )
```

- [ ] Step 7: Report failures in the closing line

Replace the final line of `run_trace`:

```python
    print(f"Wrote {out} ({len(matrix.entries)} controls, {matrix.gap_count} gaps)")
```

with:

```python
    print(
        f"Wrote {out} ({len(matrix.entries)} controls, {matrix.gap_count} gaps, "
        f"{len(matrix.covered_with_failure)} failing)"
    )
```

- [ ] Step 8: Run the tests to verify they pass

Run: `uv run pytest selftests/ -q`
Expected: PASS. Any pre-existing test asserting on the old
`Wrote ... gaps)` string or importing `traceability_warning` needs updating in
this same task.

- [ ] Step 9: Lint and commit

```bash
uvx ruff@0.15.0 check src/ src/vip_tests/ selftests/ examples/
uvx ruff@0.15.0 format src/ src/vip_tests/ selftests/ examples/
git add src/vip/report_content.py src/vip/report_html.py src/vip/report_typst.py \
        src/vip/traceability.py src/vip/cli.py selftests/
git commit -m "feat(trace): warn when a covered control's scenarios did not pass"
```

---

### Task 6: Make the coverage badge identical in both editions

Files:
- Modify: `src/vip/report_typst.py:583` (the `vip-pill` call)
- Modify: `src/vip/report_html.py:445` (the badge class)
- Modify: `report/styles.css` (add `.trace-caveat` and `.trace-warning`)
- Test: `selftests/test_report_typst.py`, `selftests/test_report_traceability.py`

Interfaces:
- Consumes: `COVERAGE_STYLE_KEY` and `COVERAGE_LABELS` from Task 4.
- Produces: nothing later tasks rely on.

- [ ] Step 1: Write the failing tests

In `selftests/test_report_typst.py`, importing the helper with
`from conftest import matrix_from_statuses` (added in Task 3):

```python
def test_coverage_badge_uses_the_same_chip_as_an_outcome():
    """vip-pill is a saturated fill with white text; the HTML edition is a chip."""
    matrix = matrix_from_statuses(statuses={"c1": ["passed"]})
    out = report_typst.render_traceability(matrix)
    assert "vip-chip" in out
    assert "vip-pill" not in out
```

In `selftests/test_report_traceability.py`, with the same import:

```python
def test_html_coverage_badge_uses_a_class_that_exists_in_styles_css():
    css = (Path(__file__).parent.parent / "report" / "styles.css").read_text()
    matrix = matrix_from_statuses(statuses={"c1": ["passed"]})
    html = report_html.render_traceability(matrix)
    for cls in ("vip-badge", "trace-caveat", "trace-warning"):
        assert f".{cls}" in css, f"{cls} is referenced by the renderer but absent from styles.css"
    assert "class='badge'" not in html
```

The CSS assertions read `styles.css` directly rather than going through the
rendered HTML, because `.trace-warning` only appears in the output when the
matrix has a warning to show. Checking the stylesheet covers both classes
whatever the matrix contains.

- [ ] Step 2: Run the tests to verify they fail

Run: `uv run pytest selftests/test_report_typst.py selftests/test_report_traceability.py -v`
Expected: FAIL. `vip-pill` is present in the Typst output, and `.vip-badge` is
in `styles.css` but `.trace-caveat` and `.trace-warning` are not.

- [ ] Step 3: Switch Typst to the chip

In `src/vip/report_typst.py`, replace:

```python
                _call("vip-pill", _lit(COVERAGE_LABELS[row.coverage]), _lit(style.color)),
```

with:

```python
                # vip-chip, not vip-pill: the HTML edition renders dark text on
                # a pale fill (outcome_badge_html), and vip-pill is a saturated
                # fill with white text. The two editions must match.
                _call(
                    "vip-chip",
                    _lit(COVERAGE_LABELS[row.coverage]),
                    _lit(style.color),
                    _lit(style.background),
                ),
```

- [ ] Step 4: Point the HTML badge at the real class

In `src/vip/report_html.py`, replace:

```python
            f"<span class='badge' style='color:{style.color};"
```

with:

```python
            f"<span class='vip-badge' style='color:{style.color};"
```

`.badge` alone has no rule in `styles.css`; the styled class is `.vip-badge`
(`report/styles.css:133`), which supplies the padding, uppercasing and radius
the badge was written to have.

- [ ] Step 5: Add the two missing CSS rules

Append to `report/styles.css`, after the `.vip-badge` block:

```css
/* Compliance traceability section (see report_html.render_traceability). The
   Typst edition renders the caveat italic and the warning as a plain
   paragraph, so these keep the two editions matched. */
.trace-caveat {
  font-style: italic;
  font-size: 0.875rem;
  color: #6b7280;
}

.trace-warning {
  font-size: 0.875rem;
  color: #b91c1c;
}
```

- [ ] Step 6: Run the tests to verify they pass

Run: `uv run pytest selftests/ -q`
Expected: PASS, including the pre-existing color drift guard in
`selftests/test_report_content.py`.

- [ ] Step 7: Lint and commit

```bash
uvx ruff@0.15.0 check src/ src/vip_tests/ selftests/ examples/
uvx ruff@0.15.0 format src/ src/vip_tests/ selftests/ examples/
git add src/vip/report_typst.py src/vip/report_html.py report/styles.css selftests/
git commit -m "fix(report): render the coverage badge identically in both editions"
```

---

### Task 7: Show a render failure in both editions, and verify the sidecar where it counts

Files:
- Modify: `src/vip/report_content.py` (add `TRACEABILITY_RENDER_FAILURE`)
- Modify: `src/vip/report_typst.py` (`render_document` gains `trace_error`)
- Modify: `report/index.qmd:77-92`
- Modify: `report/vip-report.qmd:49-66`
- Modify: `.github/workflows/example-report.yml:451-454` (the stale comment)
- Test: `selftests/test_report_typst.py`, `selftests/test_report_content.py`

Interfaces:
- Consumes: nothing from earlier tasks.
- Produces: `report_content.TRACEABILITY_RENDER_FAILURE` (a format string with
  one `{error}` field) and
  `report_typst.render_document(data, hints, matrix=None, trace_error=None)`.

- [ ] Step 1: Write the failing tests

In `selftests/test_report_content.py`:

```python
def test_render_failure_message_names_the_error():
    msg = report_content.TRACEABILITY_RENDER_FAILURE.format(error="boom")
    assert "boom" in msg
    assert "traceability" in msg.lower()
```

In `selftests/test_report_typst.py`:

```python
def test_render_document_shows_a_trace_error_instead_of_dropping_the_section():
    out = report_typst.render_document(ReportData(), {}, matrix=None, trace_error="boom")
    assert "boom" in out

def test_a_trace_error_is_escaped_for_typst():
    """An exception message can carry #, * or $, which are live Typst markup."""
    out = report_typst.render_document(
        ReportData(), {}, matrix=None, trace_error="bad #value"
    )
    assert "#value" not in out.replace('"bad \\#value"', "")
```

`ReportData()` needs no arguments: every field has a default. Import it with
`from vip.reporting import ReportData`.

- [ ] Step 2: Run the tests to verify they fail

Run: `uv run pytest selftests/test_report_typst.py selftests/test_report_content.py -v`
Expected: FAIL with `AttributeError: ... TRACEABILITY_RENDER_FAILURE` and
`TypeError: render_document() got an unexpected keyword argument 'trace_error'`.

- [ ] Step 3: Add the shared message

In `src/vip/report_content.py`, next to `TRACEABILITY_CAVEAT`:

```python
# Both editions render this identically when the section cannot be built. A
# compliance report that drops the section without saying so is the one
# outcome a regulated reader cannot detect.
TRACEABILITY_RENDER_FAILURE = "Could not render the traceability section: {error}"
```

- [ ] Step 4: Accept and render the error in the Typst backend

Change `render_document`'s signature in `src/vip/report_typst.py`:

```python
def render_document(data: ReportData, hints: dict[str, dict], matrix=None, trace_error=None) -> str:  # noqa: ANN001
```

Where the function currently decides whether to append the traceability
section, add the error branch. `trace_error` renders through `_paragraph`,
which routes the text through `_lit`, so a `#`, `*` or `$` in an exception
message is escaped rather than executed:

```python
    if trace_error:
        parts.append(_heading("Compliance Traceability"))
        parts.append(_paragraph(TRACEABILITY_RENDER_FAILURE.format(error=trace_error)))
    elif matrix is not None:
        parts.append(_heading("Compliance Traceability"))
        parts.append(render_traceability(matrix))
```

Read the existing `if matrix is not None:` block in `render_document` first and
keep its exact heading call and append order. The two branches must emit the
same heading, so a reader of the PDF sees the section start either way. Use the
module's own heading helper rather than inventing one; if it is not named
`_heading`, use the real name in both branches.

- [ ] Step 5: Verify the checksum in `report/index.qmd`

Replace the body of the `if _controls:` block:

```python
if _controls:
    _trace_error = None
    try:
        from vip.traceability import (
            build_traceability_matrix,
            load_controls,
            verify_results_checksum,
        )

        _results_path = Path("results.json")
        # Verify rather than only digest. --controls makes this a compliance
        # artifact, and the sidecar attestation in the provenance block is
        # worthless if nothing checked it. verify_results_checksum raises, and
        # the except below is now a visible marker rather than a dropped
        # section, so raising here is safe.
        _digest, _verified = verify_results_checksum(_results_path)
        _matrix = build_traceability_matrix(
            data,
            load_controls(_controls),
            results_sha256=_digest,
            results_sha256_sidecar_verified=_verified or None,
        )
        display(Markdown("## Compliance Traceability"))
        display(HTML(report_html.render_traceability(_matrix)))
    except Exception as exc:  # noqa: BLE001 - a report must render regardless
        display(Markdown("## Compliance Traceability"))
        display(Markdown(f"> {report_content.TRACEABILITY_RENDER_FAILURE.format(error=exc)}"))
```

Add `from vip import report_content` to that cell's imports if the file does not
already import it. Remove the now-unused `import hashlib` if nothing else in the
file uses it.

- [ ] Step 6: Do the same in `report/vip-report.qmd`

```python
matrix = None
trace_error = None
_controls = os.environ.get("VIP_CONTROLS")
if _controls:
    try:
        from vip.traceability import (
            build_traceability_matrix,
            load_controls,
            verify_results_checksum,
        )

        _digest, _verified = verify_results_checksum(Path("results.json"))
        matrix = build_traceability_matrix(
            data,
            load_controls(_controls),
            results_sha256=_digest,
            results_sha256_sidecar_verified=_verified or None,
        )
    except Exception as exc:  # noqa: BLE001 - a report must render regardless
        matrix = None
        trace_error = str(exc)

print("```{=typst}")
print(report_typst.render_document(data, hints, matrix, trace_error))
print("```")
```

Remove the now-unused `import hashlib` if nothing else in the file uses it.

- [ ] Step 7: Correct the stale workflow comment

In `.github/workflows/example-report.yml`, replace the comment above the
"Render the compliance report" step:

```yaml
      # VIP_CONTROLS must be absolute. Quarto renders with report/ as the
      # working directory, so a relative path resolves against report/ and the
      # control list is not found. Both documents now print a visible "could
      # not render the traceability section" marker instead of dropping it, so
      # this fails loudly rather than going green with the section missing --
      # but an absolute path is still what makes it work.
```

- [ ] Step 8: Run the tests to verify they pass

Run: `uv run pytest selftests/ -q`
Expected: PASS.

- [ ] Step 9: Render both editions for real

Run:

```bash
uv run vip verify --categories prerequisites -- -q || true
VIP_CONTROLS="$PWD/examples/21CFR_part11_validation/controls.toml" \
  uv run vip report
```

Expected: `_output/index.html` and `_output/vip-report.pdf` both produced, both
carrying a Compliance Traceability section. If Quarto is not installed locally,
say so and skip this step rather than reporting it as passed.

- [ ] Step 10: Lint and commit

```bash
uvx ruff@0.15.0 check src/ src/vip_tests/ selftests/ examples/
uvx ruff@0.15.0 format src/ src/vip_tests/ selftests/ examples/
git add src/vip/report_content.py src/vip/report_typst.py report/index.qmd \
        report/vip-report.qmd .github/workflows/example-report.yml selftests/
git commit -m "fix(report): show a traceability render failure in both editions"
```

---

### Task 8: Gate `vip report --controls` on the checksum

Files:
- Modify: `src/vip/cli.py:813-845` (the `--controls` validation block)
- Test: `selftests/test_cli_report.py`

Interfaces:
- Consumes: nothing from earlier tasks.
- Produces: nothing later tasks rely on.

- [ ] Step 1: Write the failing test

In `selftests/test_cli_report.py`, following that file's existing pattern for
invoking `run_report` with a temp report directory:

```python
def test_report_with_controls_refuses_a_mismatched_sidecar(tmp_path, capsys):
    """--controls makes this a compliance artifact; it inherits trace's strictness."""
    results = tmp_path / "results.json"
    results.write_text('{"schema_version": "1.0", "results": []}', encoding="utf-8")
    results.with_name("results.json.sha256").write_text(f"{'a' * 64}  results.json\n")
    controls = tmp_path / "controls.toml"
    controls.write_text(
        '[[control]]\nid = "c1"\ndescription = "d"\nverification = "automated"\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        run_report(_report_args(results=results, controls=controls))
    assert exc.value.code == 1
    assert "checksum mismatch" in capsys.readouterr().err


def test_report_without_controls_ignores_a_mismatched_sidecar(tmp_path, monkeypatch):
    """Plain vip report stays lenient: a report must render regardless."""
    results = tmp_path / "results.json"
    results.write_text('{"schema_version": "1.0", "results": []}', encoding="utf-8")
    results.with_name("results.json.sha256").write_text(f"{'a' * 64}  results.json\n")
    # Stub the Quarto invocation so the test asserts on the gate, not on a
    # local Quarto install; follow whatever this file already does for that.
    monkeypatch.setattr(cli, "_quarto_render", lambda *a, **k: 0)
    run_report(_report_args(results=results, controls=None))
    # No SystemExit: the mismatched sidecar is not consulted without --controls.
```

Match the `controls.toml` shape to whatever `load_controls` actually expects;
copy the smallest valid example out of `examples/21CFR_part11_validation/controls.toml`.

- [ ] Step 2: Run the test to verify it fails

Run: `uv run pytest selftests/test_cli_report.py -v -k sidecar`
Expected: FAIL. No `SystemExit` is raised, because nothing verifies the sidecar.

- [ ] Step 3: Add the verification to the gate

In `src/vip/cli.py`, add `verify_results_checksum` to the import list in the
`if getattr(args, "controls", None):` block, then add the call inside the
existing `try`, after `check_results_rows(results_dest)`:

```python
            # The sidecar too, not only the schema and the rows. A compliance
            # render is an evidence artifact, so it inherits `vip trace`'s
            # strictness in full rather than in part.
            verify_results_checksum(results_dest)
```

The existing `except (ResultsIntegrityError, ControlListError)` clause already
catches what this raises, so no new handler is needed.

- [ ] Step 4: Run the tests to verify they pass

Run: `uv run pytest selftests/test_cli_report.py -v`
Expected: PASS.

- [ ] Step 5: Lint and commit

```bash
uvx ruff@0.15.0 check src/ src/vip_tests/ selftests/ examples/
uvx ruff@0.15.0 format src/ src/vip_tests/ selftests/ examples/
git add src/vip/cli.py selftests/test_cli_report.py
git commit -m "fix(cli): verify the checksum sidecar on a compliance render"
```

---

### Task 9: Compare schema majors as numbers

Files:
- Modify: `src/vip/reporting.py:213`
- Test: `selftests/test_results_schema.py`

Interfaces:
- Consumes: nothing. Produces: nothing.

- [ ] Step 1: Write the failing test

In `selftests/test_results_schema.py`:

```python
def test_direction_is_numeric_not_lexicographic(monkeypatch, tmp_path):
    """"9" > "10" as strings; a results file at major 9 is older, not newer."""
    monkeypatch.setattr(reporting, "RESULTS_SCHEMA_VERSION", "10.0")
    p = tmp_path / "results.json"
    p.write_text('{"schema_version": "9.0", "results": []}', encoding="utf-8")
    with pytest.warns(UserWarning, match="older than"):
        reporting.load_results(p)
```

- [ ] Step 2: Run the test to verify it fails

Run: `uv run pytest selftests/test_results_schema.py -v -k lexicographic`
Expected: FAIL. The warning says "newer than".

- [ ] Step 3: Compare as integers

In `src/vip/reporting.py`, replace:

```python
            direction = "newer than" if theirs > ours else "older than"
```

with:

```python
            # int, not string: "9" > "10" lexicographically, so a string
            # compare misreports the direction once either major reaches two
            # digits. A non-numeric major is possible in a hand-edited file,
            # so fall back to the string compare rather than raising inside a
            # loader whose contract is to warn and carry on.
            try:
                newer = int(theirs) > int(ours)
            except ValueError:
                newer = theirs > ours
            direction = "newer than" if newer else "older than"
```

- [ ] Step 4: Run the tests to verify they pass

Run: `uv run pytest selftests/test_results_schema.py -v`
Expected: PASS.

- [ ] Step 5: Lint and commit

```bash
uvx ruff@0.15.0 check src/ src/vip_tests/ selftests/ examples/
uvx ruff@0.15.0 format src/ src/vip_tests/ selftests/ examples/
git add src/vip/reporting.py selftests/test_results_schema.py
git commit -m "fix(reporting): compare schema majors numerically"
```

---

### Task 10: Update the docs the behaviour changes touch

Files:
- Modify: `docs/reporting.md` (the `.sha256` sidecar section, around line 100)
- Modify: `AGENTS.md` (the `src/vip/traceability.py` row of the key-source-files table)
- Test: none. Documentation only.

Interfaces: consumes nothing, produces nothing.

- [ ] Step 1: Document the sidecar matching rule

In `docs/reporting.md`, after the `shasum -a 256 -c results.json.sha256` block,
add:

```markdown
The recorded filename is matched on its exact value first, then on its basename.
A sidecar generated from a directory above the results file records the path it
was given (`<digest>  report/results.json`) and still verifies. A multi-file
sidecar that names the file exactly keeps the stricter exact match, so it cannot
be satisfied by a same-named file in another directory.
```

- [ ] Step 2: Document the failing-control state

In `docs/reporting.md`, wherever the traceability coverage values are described,
add `FAILED` alongside `COVERED`, `NOT RUN`, `GAP` and `N/A (manual)`, described
as: a covered control with at least one tagged scenario that ran and did not
pass. If that list does not exist in the file yet, add it near the traceability
section rather than inventing a new one elsewhere.

- [ ] Step 3: Update the AGENTS.md traceability row

The row currently explains the `executed` / `covered_without_execution` split.
Add one sentence: `ControlEntry.failing` and
`TraceabilityMatrix.covered_with_failure` are the third fact, separating "a
scenario ran" from "a scenario passed", and any failing scenario demotes the
control's badge rather than only an all-failed one.

- [ ] Step 4: Run the docs drift guard

Run: `uv run pytest selftests/test_scaffold_agents_md.py -v`
Expected: PASS. This parses the real source and fails if the inventory drifts.

- [ ] Step 5: Commit

```bash
git add docs/reporting.md AGENTS.md
git commit -m "docs: describe the sidecar match rule and the failing-control state"
```

---

## Final verification

- [ ] Run the full selftest suite: `uv run pytest selftests/ -q`. Expected: every
      test passes. Report the actual count.
- [ ] Run the linter and formatter over all four directories.
- [ ] Collect the product tests as a dry run: `uv run pytest src/vip_tests/ --collect-only -q`.
- [ ] Collect the example: `uv run pytest examples/21CFR_part11_validation/ --collect-only -q`.
- [ ] Confirm `MATRIX_SCHEMA_VERSION` is still `"1.0"` and `ControlEntry.coverage`
      still has exactly three values.
