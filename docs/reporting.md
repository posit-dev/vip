# Reporting

The interactive HTML report (built with Quarto) is documented on the VIP website:

https://posit-dev.github.io/vip/report/

This page covers the machine-readable outputs a `vip verify` run produces --
`results.json`, `junit.xml`, `results.sarif` -- and the traceability export built on
top of `results.json`.

## Machine-readable outputs

Every `vip verify` run writes `report/results.json` by default. Override the path
with `--report`, or pass `--report ''` to write no results file at all. `--format`
selects which additional formats are written alongside it:

```bash
vip verify --config vip.toml --format json,junit,sarif
```

`json` (`results.json`) is always written unless `--report ''` turns it off. `junit`
and `sarif` are added as sibling files in the same directory when requested, and
they are built by reloading `results.json`, so they cannot outlive it: asking for
either while disabling the results file is refused up front rather than after a
full run that would produce nothing. `--ci` is a preset that turns on
`json,junit,sarif` together with concise tracebacks, so it conflicts with
`--report ''` for the same reason.

### `results.json` field inventory

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-08-28T12:00:00+00:00",
  "deployment_name": "example",
  "exit_status": 0,
  "vip_version": "2026.8.3",
  "run_duration_seconds": 42.1,
  "python_version": "3.12.4",
  "platform": "macOS-14.5-arm64-...",
  "basic_mode": false,
  "products": {
    "connect": {"enabled": true, "url": "...", "version": null, "configured": true},
    "workbench": {"enabled": true, "url": "", "version": null, "configured": false}
  },
  "results": [
    {
      "nodeid": "...",
      "outcome": "passed",
      "markers": ["connect", "control-audit-trail-publish"],
      "scenario_title": "...",
      "started_at": "2026-08-28T12:00:01+00:00",
      "finished_at": "2026-08-28T12:00:02+00:00"
    }
  ],
  "execution": {
    "hostname": "ci-runner-01",
    "git": { "commit": "...", "branch": "...", "dirty": false, "remote": "https://github.com/org/repo" },
    "ci": { "provider": "github", "run_id": "...", "run_url": "...", "job": "verify" },
    "performed_by": { "identity": "octocat", "source": "github" }
  }
}
```

- `schema_version` -- versioned independently of VIP itself. The minor number bumps
  for an additive change (a new field). The major number bumps for a removal, a
  rename, or a change in the meaning of an existing field. A file with no
  `schema_version` at all predates versioning and is treated as pre-1.0.
- `started_at` / `finished_at` -- per-test UTC ISO 8601 timestamps, covering the call
  phase only (fixture setup is excluded, except that a setup-phase skip records setup
  start). `None` for a `results.json` written before these fields existed.
- `execution` -- attribution for the run that produced this evidence: which host ran
  it, which git commit/branch it ran from (dirty flag, remote with any credential
  stripped out of the URL), which CI job (GitHub Actions, GitLab CI, or Jenkins)
  ran it, if any, and who performed it. To omit this block entirely, pass the
  pytest-level option after `--`: `vip verify --config vip.toml --
  --vip-no-attribution`. There is no `vip verify` flag of its own for this. Useful
  if a deployment's policy is not to record hostnames, CI identifiers or an
  operator identity in an archived artifact.
- `execution.performed_by` -- the operator the run is attributable to, and `source`
  says where that value came from. Set `VIP_PERFORMED_BY` to name the person
  accountable for the run (`source: "explicit"`). Otherwise VIP reads the CI
  system's own actor (`GITHUB_ACTOR`, `GITLAB_USER_LOGIN`, `BUILD_USER_ID`), then
  falls back to the local login (`source: "login"`). `source` stays attached to the
  value because a reader seeing a service-account name needs to know whether a
  human typed it. FDA's Computer Software Assurance guidance asks the record of an
  assurance activity to state who performed the testing alongside the date, which
  is why this exists. The rest of the block identifies a machine, not a person.

Both report editions render the attribution too, so the archived artifact
includes it rather than only the machine-readable output. They render five of
these fields -- `performed_by` (qualified by its `source` unless that source is
`explicit`), `hostname`, `git.commit` (flagged when `dirty`), `git.branch`, and
`ci.run_url` or `ci.run_id`. `git.remote`, `ci.provider` and `ci.job` stay in
`results.json` only: the remote and the job name add table width without adding
much a reviewer can act on, and the provider is already evident from the run
URL. Read `results.json` itself if you need the full block.

Be precise about what `python_version`, `platform`, and `execution.hostname`
describe: they are properties of the machine that ran `vip verify` -- the VIP
runner -- not the Connect/Workbench/Package Manager deployment under test. The
`products` table is what identifies the system under test (its name, URL, version,
and whether it was configured for this run). Don't read the runner's platform string
as evidence about the deployment. It isn't.

### Schema compatibility policy

An unknown schema minor is accepted (fields you don't recognize are additive and
safe to ignore), but an unknown schema major is refused. The two consumers of
`schema_version` apply this policy differently on purpose:

- `vip.reporting.load_results` -- used by `vip report` and the Quarto notebooks
  (`report/index.qmd`, `report/details.qmd`) -- only warns on an unknown major. It
  runs inside a notebook cell, where raising would surface as an unreadable
  traceback instead of a rendered report.
- `vip trace` hard-errors on an unknown major (see `check_results_schema` in
  `src/vip/traceability.py`). A traceability matrix built against a `results.json`
  whose shape it doesn't understand is not something you want silently degraded --
  it runs from a shell, where a clear error message is the right outcome.

### The `.sha256` sidecar

Every `results.json` write also produces a `results.json.sha256` sidecar next to it,
in the standard `shasum` format:

```
<hex digest>  results.json
```

Verify it with:

```bash
shasum -a 256 -c results.json.sha256
```

The recorded filename is matched on its exact value first, then on its basename.
A sidecar generated from a directory above the results file records the path it
was given (`<digest>  report/results.json`) and still verifies. A multi-file
sidecar that names the file exactly keeps the stricter exact match, so it cannot
be satisfied by a same-named file in another directory.

This is tamper-evidence within a trusted pipeline, not tamper-proofing. Anyone who
can edit `results.json` can also regenerate the sidecar to match, so it does not
resist a motivated forger. What it does catch is the class of accidents that
actually happen to archived CI artifacts: corruption in transit, a truncated
upload, or someone hand-editing the file and forgetting to update the checksum
alongside it. Treat a checksum mismatch as "this file is not what the pipeline
produced," not as "this file has not been tampered with."

## Traceability export

`vip trace` joins `results.json` against a `controls.toml` control list and emits a
control-to-scenario traceability matrix, for suites that tag scenarios with
`@control-<slug>` Gherkin tags (see `docs/test-architecture.md` for the tagging
convention).

### `controls.toml` format

```toml
[controls.audit-trail-publish]
description = "Deployment of content is recorded with actor and timestamp"
reference = "21 CFR 11.10(e)"
risk = "high"
verification = "automated"
responsibility = "shared"
notes = "Retention duration of the audit log is a customer configuration decision."

[controls.personnel-training]
description = "Personnel have the education, training and experience to perform their tasks"
reference = "21 CFR 11.10(i)"
risk = "medium"
verification = "procedural"
responsibility = "customer"
notes = "Evidenced by training records in your QMS. No automated test can establish this."
```

`description` is required. `verification` defaults to `"automated"` and must be one
of `"automated"`, `"manual"`, or `"procedural"`. VIP is regulation-agnostic: it
passes `reference`, `risk`, `responsibility`, and `notes` through to the output
verbatim without interpreting them. The `[controls.<id>]` key is the id a scenario
references with `@control-<id>` (with the `control-` tag prefix stripped).

Those six keys plus `extra` are the whole recognised set, and any other key is an
error. Rejecting rather than ignoring is what catches a misspelled `referance`
before it vanishes from the matrix a reviewer reads. Put your own fields in an
`extra` table:

``` toml
[controls.audit-trail.extra]
phase = "OQ"
sop = "SOP-QA-014"
```

Its keys must not start with a character a spreadsheet evaluates as a formula,
since a key becomes a CSV header cell and TOML permits a quoted key like
`"=HYPERLINK(...)"`. Its values must be strings, must not collide with an
existing column name, and
are passed through untouched: each becomes a trailing CSV column (appended after
the fixed set, so `CSV_COLUMNS` stays an identical leading prefix across every
customer's export) and an `extra` object per control in the JSON. Neither report
edition renders them, because the table has no width for a variable number of
columns.

### The three coverage outcomes

A control's row in the matrix gets one of three `coverage` values:

- `covered` -- at least one scenario is tagged `@control-<id>`, and its result is
  attached. Coverage records that a scenario is tagged, not that it executed: a
  skipped scenario still counts as covered, and its `skipped` status is reported
  alongside. See "Covered is not the same as executed" below, which matters more
  than it sounds like it should.
- `gap` -- no scenario has the tag, and `verification = "automated"` (the
  default). This is the one that should worry you.
- `not_automatable` -- no scenario has the tag, but `verification` is
  `"manual"` or `"procedural"`. This is *not* a gap. A control satisfied by a
  personnel training record, a physical procedure, or a signature-manifestation
  requirement that Posit Team's platform doesn't implement has no automated
  scenario to point to, and reporting it as a gap would train reviewers to ignore
  every real gap alongside it. Distinguishing the two is why `verification` exists
  at all -- collapsing `not_automatable` into `gap` would make the matrix useless
  for exactly the controls that need a human process instead of a test.

### Coverage display states

The rendered report displays coverage as `COVERED`, `FAILED`, `UNPROVEN`,
`NOT RUN`, `GAP`, or `N/A (manual)`:

- `COVERED` -- at least one tagged scenario ran and passed.
- `FAILED` -- a covered control with at least one tagged scenario that ran and did
  not pass.
- `UNPROVEN` -- a covered control with at least one tagged scenario that VIP was
  asked to run and could not (`vip.attest.unproven`).
- `NOT RUN` -- at least one tagged scenario is present, but all of them skipped or
  were not executed.
- `GAP` -- no tagged scenario is present and `verification = "automated"`.
- `N/A (manual)` -- no tagged scenario is present but `verification` is `"manual"`
  or `"procedural"`.

A control can satisfy more than one of these at once, and the display column
shows only the loudest. The order is `FAILED`, then `UNPROVEN`, then `NOT RUN`:
a control that ran and failed is the strongest claim against it. An
all-unproven control is also not executed, but `UNPROVEN` is the more
specific of the two, so it takes priority. Read the per-scenario `status` column for the rest.

### Covered is not the same as executed

A scenario can run and skip itself -- the endpoint it probes is absent from this
deployment, there is no data to inspect, a version gate excludes it -- and it
still keeps its control tag in the results file. A control tagged only by
such scenarios is therefore `covered`, and a matrix can read `covered: 3,
gaps: 0` while nothing was verified at all. That is the most misleading thing
this export can do, so it is reported three ways rather than left implicit:

- `vip trace` warns on stderr, naming the affected control ids.
- The JSON `summary` reports `covered_and_executed` (a tagged scenario ran,
  whether or not it passed), `covered_not_executed` (a tagged scenario is
  present but none ran), `covered_failed` (a tagged scenario ran and did not
  pass), and `covered_unproven` (a tagged scenario was a check VIP could not
  run). These are not a partition: a failing control counts toward both
  `covered_and_executed` and `covered_failed`, since it did run and it did not
  pass, and an all-unproven control counts toward both `covered_not_executed`
  and `covered_unproven`. The rendered report's own summary table partitions
  differently -- it splits the display value into mutually exclusive rows,
  `Covered, executed and passing`, `Covered, not executed`, `Covered, failing`
  and `Covered, not verified`, so each control is counted once. Do not expect
  the report table and the JSON `summary` to add up the same way.
- The JSON has a `covered_without_execution` list of control ids and a
  `covered_with_unproven` list.

A version-gated scenario (`na_version`) counts as not executed too, for the same
reason: it ran no assertions. So does an `unproven` one, which is the reason
`covered_unproven` exists alongside the other counts: an unproven skip is
neither an execution nor a failure, so a control with one passing scenario and
one unproven scenario is invisible to `covered_not_executed` and
`covered_failed` both, and part of the control still went unchecked.

An unconfigured product is a different case, and it fails the opposite way.
Those scenarios are deselected rather than skipped -- excluded from the run
entirely, so they never reach `results.json` -- and a control tagged only by
them has nothing to join against, so it reports as a `gap`. An underconfigured
run therefore understates coverage rather than overstating it, which is the
safer direction, but a reader who takes the gap at face value concludes the
suite lacks a check it has. The `products` block records what was actually
under test. Read it alongside the gaps.

Read `gaps: 0` together with `covered_not_executed` and `covered_unproven`.
Zero gaps and a non-zero `covered_not_executed` means the controls are mapped
and the evidence is missing. A non-zero `covered_unproven` means VIP was asked
for evidence it could not produce, which is the difference between a check with
nothing to test and a check that never got to run.

### Worked example

```bash
vip verify --config vip.toml --extensions ./examples/21CFR_part11_validation
vip trace --results report/results.json --controls ./examples/21CFR_part11_validation/controls.toml
```

`vip trace` defaults to CSV on stdout. Pass `--format json` for full fidelity output
(including nested match details), or `--output matrix.csv` / `--output matrix.json`
to write to a file instead. With `--output` and no `--format`, the format is taken
from the file extension, so `--output matrix.json` writes JSON. An explicit
`--format` always wins and warns when it disagrees with the extension.

Both formats include the results digest. CSV repeats `generated_at`, `vip_version`,
`results_sha256` and `exit_status` on every row, which is enough to match the
archived spreadsheet to the exact `results.json` it came from. The full
provenance block -- the products and versions under test, the runner host, and the CI
run -- is JSON only, because it does not flatten into columns. CSV is the more portable format for spreadsheet tools,
but it alters what a non-Excel reader sees: any cell whose value begins with
`= + - @` or a leading tab/carriage-return/newline is apostrophe-prefixed
(`'=SUM(...)` instead of `=SUM(...)`) to stop it from being evaluated as a formula
when opened in Excel. JSON output is not altered this way -- use it when exact
fidelity to the underlying value matters more than spreadsheet safety.

Control ids become pytest marker names, so they may use only letters, digits,
`-`, `.` and `_`. A `:` or `(` in an id (`11.10(a)`, `iso:27001`) truncates the
name pytest registers, which aborts collection under `--strict-markers`. VIP
warns and skips registering such a tag. Write `11-10-a` instead.

### In the rendered report

`vip report --controls PATH` adds a Compliance Traceability section to both the
HTML report and the PDF, with the summary counts, the per-control coverage,
and the scenario and timestamp evidencing each one. Without `--controls` there is
no section and nothing changes, which is the case for every run that has no
control list.

```bash
vip report --results report/results.json --controls ./my-tests/controls.toml
```

The control list is scoped to that one render, passed to Quarto as `VIP_CONTROLS`
rather than copied into the report directory. That directory survives between
runs, so a copied file would make every later plain `vip report` sprout a
compliance section nobody asked for, built from a stale list. Rendering the
report documents directly with `quarto render` therefore needs `VIP_CONTROLS`
set by hand.

The section repeats the same caveat the CSV and JSON exports state, because the
report is the artifact that gets archived and handed on: coverage records that a
scenario is tagged, a control shown as NOT RUN has a tagged scenario that ran
and skipped itself, and a control shown as UNPROVEN has one VIP was asked to run
and could not. See `examples/21CFR_part11_validation/VALIDATION-PACKAGE.md` for how these
outputs map onto a GxP
validation package, and which parts of one VIP cannot supply.

`vip scaffold --template 21cfr-part11-validation --output DIR` generates a starting point
with a worked `controls.toml`, a tagged feature file, and the client methods
(`list_audit_logs`, `audit_log_allowed_methods`, `unauthenticated_status`) the
example scenarios use.
