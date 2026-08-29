# Reporting

The interactive HTML report (built with Quarto) is documented on the VIP website:

https://posit-dev.github.io/vip/report/

This page covers the machine-readable outputs a `vip verify` run produces --
`results.json`, `junit.xml`, `results.sarif` -- and the traceability export built on
top of `results.json`.

## Machine-readable outputs

Every `vip verify` run writes `report/results.json` by default; override the path
with `--report`. Note that `--report ''` does NOT disable the report -- `vip verify`
only forwards the option when it is non-empty, so an empty value falls back to the
default path. To suppress the file entirely, pass the pytest-level option through:
`vip verify --config vip.toml -- --vip-report=`. `--format` selects which additional
formats are written alongside it:

```bash
vip verify --config vip.toml --format json,junit,sarif
```

`json` (`results.json`) is always written regardless of `--format`; `junit` and
`sarif` are added as sibling files in the same directory when requested. `--ci` is a
preset that turns on `json,junit,sarif` together with concise tracebacks.

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
    "ci": { "provider": "github", "run_id": "...", "run_url": "...", "job": "verify" }
  }
}
```

- `schema_version` -- versioned independently of VIP itself. The minor number bumps
  for an additive change (a new field); the major number bumps for a removal, a
  rename, or a change in the meaning of an existing field. A file with no
  `schema_version` at all predates versioning and is treated as pre-1.0.
- `started_at` / `finished_at` -- per-test UTC ISO 8601 timestamps, covering the call
  phase only (fixture setup is excluded, except that a setup-phase skip records setup
  start). `None` for a `results.json` written before these fields existed.
- `execution` -- attribution for the run that produced this evidence: which host ran
  it, which git commit/branch it ran from (dirty flag, remote with any credential
  stripped out of the URL), and which CI job (GitHub Actions, GitLab CI, or Jenkins)
  ran it, if any. To omit this block entirely, pass the pytest-level option after
  `--`: `vip verify --config vip.toml -- --vip-no-attribution`. There is no
  `vip verify` flag of its own for this. Useful if a deployment's policy is not to
  record hostnames or CI identifiers in an archived artifact.

Be precise about what `python_version`, `platform`, and `execution.hostname`
describe: they are properties of the machine that ran `vip verify` -- the VIP
runner -- not the Connect/Workbench/Package Manager deployment under test. The
`products` table is what identifies the system under test (its name, URL, version,
and whether it was configured for this run). Don't read the runner's platform string
as evidence about the deployment; it isn't.

### Schema compatibility policy

An unknown schema minor is accepted (fields you don't recognize are additive and
safe to ignore); an unknown schema major is refused. The two consumers of
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

`description` is required; `verification` defaults to `"automated"` and must be one
of `"automated"`, `"manual"`, or `"procedural"`. VIP is regulation-agnostic: it
carries `reference`, `risk`, `responsibility`, and `notes` through to the output
verbatim without interpreting them. The `[controls.<id>]` key is the id a scenario
references with `@control-<id>` (with the `control-` tag prefix stripped).

### The three coverage outcomes

A control's row in the matrix gets one of three `coverage` values:

- `covered` -- at least one scenario tagged `@control-<id>` ran and its result is
  attached.
- `gap` -- no scenario carries the tag, and `verification = "automated"` (the
  default). This is the one that should worry you.
- `not_automatable` -- no scenario carries the tag, but `verification` is
  `"manual"` or `"procedural"`. This is *not* a gap. A control satisfied by a
  personnel training record, a physical procedure, or a signature-manifestation
  requirement that Posit Team's platform doesn't implement has no automated
  scenario to point to, and reporting it as a gap would train reviewers to ignore
  every real gap alongside it. Distinguishing the two is why `verification` exists
  at all -- collapsing `not_automatable` into `gap` would make the matrix useless
  for exactly the controls that need a human process instead of a test.

### Worked example

```bash
vip verify --config vip.toml --extensions ./examples/part11_validation
vip trace --results report/results.json --controls ./examples/part11_validation/controls.toml
```

`vip trace` defaults to CSV on stdout; pass `--format json` for full fidelity output
(including nested match details), or `--output matrix.csv` / `--output matrix.json`
to write to a file instead. CSV is the more portable format for spreadsheet tools,
but it alters what a non-Excel reader sees: any cell whose value begins with
`= + - @` or a leading tab/carriage-return/newline is apostrophe-prefixed
(`'=SUM(...)` instead of `=SUM(...)`) to stop it from being evaluated as a formula
when opened in Excel. JSON output is not altered this way -- use it when exact
fidelity to the underlying value matters more than spreadsheet safety.

`vip scaffold --template part11-validation --output DIR` generates a starting point
with a worked `controls.toml`, a tagged feature file, and the client methods
(`list_audit_logs`, `audit_log_allowed_methods`, `unauthenticated_status`) the
example scenarios use.
