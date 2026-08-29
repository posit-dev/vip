# Traceability review fixes: design

Date: 2026-08-29
Branch: feat/part11-traceability

## Why

A review of `feat/part11-traceability` found eight defects, all verified against
the working tree. Two of them make VIP refuse evidence that was never tampered
with. Two more let a compliance artifact render a failing control as green. The
rest are divergences between the HTML and PDF report editions, plus one cosmetic
comparison bug.

The branch is a compliance feature. Both failure directions are expensive here:
refusing good evidence blocks a validation run, and passing bad evidence is worse
than not having the tool.

## Decisions taken

These were settled during brainstorming and are the constraints the design works
within.

1. A failed control gets a new value at the display layer only.
   `ControlEntry.coverage` keeps its three values (`covered`, `gap`,
   `not_automatable`), so the `coverage` column in the CSV and JSON matrix is
   unchanged and downstream consumers see nothing new there.
2. Sidecar filename matching tries the exact recorded name first and falls back
   to a basename comparison only when no entry matched exactly.
3. `vip report --controls` verifies the sha256 sidecar under the same gate that
   already runs the schema and row checks.
4. Any failing scenario demotes a control's badge to red, not only an
   all-failed control. A green badge above a visible failing scenario row is the
   misreading this change exists to prevent. The cost is accepted: a control
   checked by three scenarios goes red when one of them flakes.

## Section 1: Sidecar trust

### The defect

`verify_results_checksum` (`src/vip/traceability.py:490`) selects sidecar entries
with `name == p.name`, comparing against the bare filename. A sidecar generated
from a directory above the results file records a path, so nothing matches and
the function raises `ResultsIntegrityError`.

Reproduced:

```
$ shasum -a 256 report/results.json > report/results.json.sha256
$ vip trace --results report/results.json --controls controls.toml
Error: checksum sidecar report/results.json.sha256 does not record an entry for
results.json; it names report/results.json. Regenerate it, or delete it to
proceed without verification.
$ echo $?
1
```

`shasum -a 256 report/results.json` is the natural command for an operator who is
not standing in `report/`, and it is what a CI job re-hashing an archived
artifact from the workspace root produces. `docs/reporting.md` documents the bare
name form, so the docs are not wrong, but they do not cover the case that breaks.

`_rehome_sidecar` (`src/vip/cli.py:1660`) has the mirror of the same defect and
two more edges.

### The fix

In `verify_results_checksum`, keep the exact comparison as the primary key. When
`named` comes back empty and before the unnamed-entry fallback, retry comparing
`PurePosixPath(name).name` against `p.name`. A single-file sidecar written from
any directory verifies. A multi-file sidecar that already records the exact name
takes the first branch and keeps today's strict behaviour, so the disambiguation
the existing comment describes is preserved.

In `_rehome_sidecar`, three changes:

- The `recorded in (None, src_name)` test gains the same basename fallback, so a
  path-qualified line is rewritten to the destination name rather than copied
  through verbatim. Copying it through produces a rehomed sidecar that then fails
  verification at the destination, which is the false tamper alarm the function
  exists to prevent.
- Catch `UnicodeDecodeError` from `src.read_text(encoding="utf-8-sig")`. The call
  site at `src/vip/cli.py:779` catches only `OSError`, so a corrupt sidecar
  currently reaches the user as a traceback. `verify_results_checksum` already
  catches `UnicodeDecodeError` on the identical read, and the two paths should
  agree.
- When the source sidecar exists but parses to zero entries, unlink the
  destination instead of writing an empty file. `verify_results_checksum`
  deliberately refuses an empty sidecar as the truncated-upload case, so writing
  one manufactures the very state the reader is told to distrust. No sidecar is a
  documented benign state.

## Section 2: Coverage honesty

### The defect

`build_traceability_matrix` sets `coverage = "covered"` whenever a control has any
tagged scenario. `ControlEntry.executed` separates "a scenario is tagged" from "a
scenario ran", and `display_coverage` (`src/vip/report_content.py:443`) demotes
an all-skipped control to amber. Nothing separates "a scenario ran" from "a
scenario passed".

Reproduced with a results file whose only `control-record-retention` row has
outcome `failed`: the JSON matrix reports `coverage: "covered"`,
`covered_and_executed: 2`, exit status 0, and no warning. The report renders a
green COVERED badge, because `COVERAGE_STYLE_KEY` maps `covered` onto the
`passed` style.

### The fix

`ControlEntry` gains a `failing` property:

```python
@property
def failing(self) -> bool:
    """Whether any tagged scenario produced a result that was not a pass."""
    return any(
        m.status not in NON_EXECUTING_STATUSES and m.status != "passed"
        for m in self.matches
    )
```

Named `failing`, not `verified` or `passed`. `ControlSpec.verification` already
means automated/manual/procedural and `results_sha256_sidecar_verified` already
means checksum-checked, both in this file, so a third meaning on that word would
be a real ambiguity. `passed` reads as a question about the whole control, which
under decision 4 is not the question being asked.

Defined by exclusion rather than by enumerating failure statuses. `error` is a
reachable outcome alongside `failed` (`src/vip/plugin.py:1411`), and an
enumerated list would let an errored control read green. Non-executing statuses
are excluded by reusing `NON_EXECUTING_STATUSES`, so a skip never counts against
a control.

`display_coverage` gains one branch:

```python
def display_coverage(entry):
    if entry.coverage == "covered" and entry.failing:
        return "covered_failed"
    if entry.coverage == "covered" and not entry.executed:
        return "covered_not_executed"
    return entry.coverage
```

The two new branches cannot both apply, because `failing` is false whenever
nothing executed. The resulting truth table over a control's match statuses:

| Statuses | Display |
|---|---|
| all passed | covered (green) |
| passed + skipped | covered (green) |
| passed + failed | covered_failed (red) |
| failed only | covered_failed (red) |
| error only | covered_failed (red) |
| skipped only | covered_not_executed (amber) |

Row three is decision 4. A control checked by several scenarios goes red when one
of them fails, and the per-scenario evidence column shows which.

`TraceabilityMatrix` gains `covered_with_failure`, mirroring
`covered_without_execution` in both shape and docstring intent. It feeds:

- A new warning in `run_trace` (`src/vip/cli.py`), printed alongside the existing
  unrecognized-tag and covered-not-executed warnings.
- The closing `Wrote ... (N controls, M gaps)` line, which gains a failure count.
- A `covered_failed` key in `render_json`'s summary block.
- `traceability_warning` (`src/vip/report_content.py:500`), so the rendered
  report states it too.

`MATRIX_SCHEMA_VERSION` stays at `1.0`. The `coverage` field's value set is
unchanged under decision 1, and a new summary key is additive.

## Section 3: Report parity, and a real attestation

### Three defects, one change

The coverage badge renders differently in the two editions. `report_html`
(`src/vip/report_html.py:445`) emits an inline `color` and `background` pair,
dark text on a pale fill, matching `outcome_badge_html`. `report_typst`
(`src/vip/report_typst.py:583`) calls `vip-pill(label, style.color)`, a saturated
fill with white text. The Typst equivalent of the HTML treatment is
`vip-chip(label, fg, bg)`, which `outcome_chip` already uses at
`src/vip/report_typst.py:210`.

The HTML classes `badge`, `trace-caveat` and `trace-warning` do not exist in
`report/styles.css`. The styled class is `.vip-badge` (`report/styles.css:133`),
so the coverage badge currently renders as unpadded, non-uppercased inline text.

On an error, `report/index.qmd:90` displays `Could not render the traceability
section: <exc>` while `report/vip-report.qmd` sets `matrix = None` and renders
nothing at all. CLAUDE.md requires the two editions stay in step.

### The fix

`covered_failed` maps onto the existing `failed` outcome style in
`COVERAGE_STYLE_KEY`, reusing the outcome palette exactly as the comment above
that dict describes, so the drift guard in `selftests/test_report_content.py`
keeps working unchanged. `COVERAGE_LABELS` gains `covered_failed: "FAILED"`. Two
red labels result, GAP and FAILED, which is intended: both mean the control is
not evidenced.

Typst switches to `vip-chip(label, style.color, style.background)`. The HTML
badge points at `.vip-badge`. `styles.css` gains real `.trace-caveat` and `.trace-warning` rules rather than
those paragraphs dropping their classes, because the Typst edition renders the
caveat italic (`report_typst.render_traceability` passes `italic=True`) and the
two editions have to match.

The render-failure sentence moves into `report_content` so both editions word it
identically, and `vip-report.qmd` displays it instead of silently rendering
nothing. On the Typst side the exception text passes through `_lit`, because an
exception message is exactly the dynamic value that rule exists for.

### Why decision 3 needs the qmd cells

`.github/workflows/example-report.yml:456` renders the compliance report with a
raw `quarto render`, so it never enters `run_report` and never sees a CLI gate.
The qmd cells rebuild the matrix themselves and pass no sidecar argument, so
`results_sha256_sidecar_verified` stays `None` in the rendered provenance no
matter what the CLI checked.

Adding `verify_results_checksum` to `run_report`'s existing try block is still
correct and still goes in. But for the attestation to mean anything in the report
a regulated reader actually opens, both qmd cells must attempt verification
inside their own try block and pass the result into
`build_traceability_matrix`. `index.qmd`'s comment currently explains that it
computes the digest directly because `verify_results_checksum` raises by design.
That reasoning holds only while there is nowhere to show the failure. With the
shared render-failure marker from the previous subsection there is, so a
`ResultsIntegrityError` becomes a visible line in both editions rather than a
missing section.

The half-stale comment at `.github/workflows/example-report.yml:452` is updated
in the same change. It claims both documents swallow the error silently, which
stopped being true of `index.qmd`.

## Section 4: Loose end

`src/vip/reporting.py:213` computes the schema-version warning direction with
`theirs > ours` on strings. With `RESULTS_SCHEMA_VERSION = "1.0"` every reachable
input compares correctly today, and it only misreports once VIP's own major
reaches double digits. A guarded `int()` conversion costs one line, so it goes in
rather than being left as a trap.

## Testing

Every fix gets a selftest. New or extended files:

- `selftests/test_results_checksum.py`: a path-qualified single-file sidecar
  verifies; a multi-file sidecar recording the exact name keeps its current
  strict behaviour.
- A rehome test module: a path-qualified line is rewritten to the destination
  name and verifies at the destination; a whitespace-only source unlinks the
  destination rather than writing an empty file; a sidecar with undecodable bytes
  produces a warning, not a traceback.
- `selftests/test_traceability_matrix.py`: a control whose only scenario failed;
  a control mixing a pass and a failure; a control whose only scenario errored; a
  control mixing a pass and a skip stays green.
- `selftests/test_trace_cli.py`: the failure warning fires, and the closing line
  reports the failure count.
- `selftests/test_report_content.py`: both backends render the same coverage
  label set, alongside the existing color drift guard.
- `selftests/test_cli_report.py`: `vip report --controls` refuses a results file
  whose sidecar disagrees.

## Out of scope

No unrelated refactoring of `src/vip/traceability.py`. No change to the
`coverage` field's three values, and no `MATRIX_SCHEMA_VERSION` bump.
