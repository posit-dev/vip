# Design: control tagging, traceability export, and a Part 11 example

## Context

Someone is looking for VIP to produce something close to an automated 21 CFR
Part 11 traceability matrix: a mapping from regulatory control to timestamped
test evidence. VIP already produces timestamped, versioned, machine-readable
per-check results (`report/results.json`, JUnit XML, SARIF), and its Gherkin
feature files are already written as plain-language requirement statements.
What's missing is a way to attach a control ID to a scenario, a way to turn
that into an actual matrix, and a worked example showing what real Part
11-flavored scenarios look like.

PDF rendering of the final matrix is being handled by a separate team and is
explicitly out of scope here. A historical/longitudinal evidence store across
runs (needed for a true deviation log) was considered and explicitly dropped
for this round — VIP already emits one timestamped file per run; whoever owns
long-term archiving can accumulate those without any new VIP storage code.

## Goals

- Let a scenario declare which regulatory control(s) it satisfies, using a
  mechanism that's already wired into VIP's reporting pipeline.
- Produce a control -> scenario -> status -> timestamp matrix from a
  `results.json`, in a form a downstream PDF/report generator (or a
  spreadsheet) can consume directly.
- Ship a worked, opt-in example of real Part 11-flavored scenarios so
  customers have a concrete starting point rather than an abstract mechanism.
- Document all of the above so it doesn't rot as an undiscovered feature.

## Non-goals

- No PDF generation (a separate team owns that).
- No historical/deviation tracking across multiple runs.
- No VIP-shipped canonical CFR Part 11 control taxonomy. The control list is
  supplied by whoever owns the regulatory mapping; VIP stays
  regulation-agnostic the same way it doesn't hardcode what "GxP" means today.

## Design

### 1. Control tagging convention

A scenario that satisfies a compliance control carries one or more Gherkin
tags of the form `@control-<slug>`, where `<slug>` is a free-form identifier
chosen by whoever owns the control list (e.g. `@control-cfr-11-10-e`,
`@control-audit-trail-publish`). This is a plain Gherkin tag, not a new VIP
mechanism:

- A scenario can carry multiple `@control-*` tags (one test can satisfy
  several controls).
- A control can be satisfied by multiple scenarios (tag all of them with the
  same slug).
- pytest-bdd's default `pytest_bdd_apply_tag` hook turns any tag into a
  pytest marker via `getattr(pytest.mark, tag)` — this works with hyphens
  since it's dynamic attribute access, not literal Python attribute syntax.
- VIP's plugin already captures every marker on a test into
  `TestResult.markers` (`plugin.py` around the `iter_markers()` call feeding
  `pytest_runtest_logreport`), which already flows into `results.json` and
  the SARIF `ruleId`/ `logicalLocations` output. No plugin or reporting
  schema change is needed to carry the tag through.

Data flow end to end:

```
.feature @control-<slug> tag
  -> pytest-bdd marker (pytest_bdd_apply_tag)
  -> TestResult.markers in results.json / SARIF
  -> vip trace joins against a supplied control list
  -> matrix (CSV/JSON)
  -> consumed by the PDF pipeline (out of scope here)
```

### 2. Traceability export (`vip trace`)

A new pure function in `src/vip/reporting.py`:

```python
def build_traceability_matrix(
    data: ReportData,
    controls: dict[str, str],
    tag_prefix: str = "control-",
) -> TraceabilityMatrix:
    ...
```

For each `control_id` in the supplied `controls` dict (control ID ->
description), it scans `data.results` for any result whose `markers`
includes `f"{tag_prefix}{control_id}"` and produces one `ControlEntry`:

- `control_id`, `description` (from the `controls` dict)
- the matching scenario title(s)
- each match's `status` (reusing `TestResult.status`, so an N/A-by-version
  skip renders distinctly from an ordinary skip)
- the run's `generated_at` / `vip_version` for provenance

A control with zero matching scenarios is reported as a coverage gap rather
than silently omitted. A `control-*` tag found in the results that is *not*
present in the supplied `controls` dict is reported as an "unrecognized
control tag" warning — this catches typos (`@control-cfr-11-10e` vs
`@control-cfr-11-10-e`) at export time instead of silently losing coverage.

CLI surface (new subcommand in `src/vip/cli.py`):

```
vip trace --results report/results.json --controls path/to/controls.toml \
    [--tag-prefix control-] [--format csv|json] [--output path]
```

`controls.toml` is a simple `[controls]` table of `control_id = description`
pairs, loaded with `tomllib` (already imported in `reporting.py`). Output
defaults to stdout as CSV (the natural input to a downstream PDF/qualification
protocol generator or a spreadsheet); JSON is available for programmatic
consumption.

### 3. New example: `examples/part11_validation/`

Mirrors the existing `examples/cross_product_validation/` structure and the
four-layer architecture, registered in the template registry (added in #611)
so it's reachable via `vip scaffold --template part11-validation --output DIR`:

- `test_part11_validation.feature` — a small, illustrative scenario set, each
  tagged with both a product marker (`@connect`/`@workbench`) and a
  `@control-*` tag:
  - Audit trail on publish: Connect records actor + timestamp when content is
    deployed (`@control-audit-trail-publish`), verified via the Connect API
    client.
  - Privileged-action access control: a non-admin user is denied a
    privileged action, e.g. deleting another user's content
    (`@control-access-control-privileged-action`). Illustrative here, not a
    duplicate of `security/test_auth_policy.py` — the README points there
    for the fuller reference implementation.
  - Audit-log non-deletability: a non-admin cannot delete or alter an
    existing audit-trail entry via the API (`@control-record-retention`).
- `test_part11_validation.py` — thin step definitions; logic pushed into
  `clients/connect.py` (extended only if a needed method doesn't already
  exist).
- `conftest.py` — override-fixture pattern matching the existing example
  (e.g. which privileged action to exercise).
- `controls.toml` — a sample control list (the 3 entries above) demonstrating
  the format `vip trace` expects, so a customer sees a working example of
  both halves: tagged scenarios and the control list that names them.
- `README.md` — states plainly that this is a *template*, not a certified
  Part 11 test set. Customers replace/extend `controls.toml` and add their
  own scenarios for their actual regulatory mapping. Documents the
  `@control-*` convention and points at `vip trace`.

### 4. Testing

- `selftests/` coverage for `build_traceability_matrix`: full coverage, a
  coverage gap, an unrecognized-tag warning, one control satisfied by
  multiple scenarios.
- A selftest exercising the `vip trace` CLI end-to-end against a fixture
  `results.json` + `controls.toml`, checking both CSV and JSON output.
- `examples/part11_validation` collected via `--collect-only` in CI, the same
  way `cross_product_validation` already is.
- `selftests/test_scaffold_agents_md.py` — verify the new example doesn't
  need an inventory update (it reuses existing fixtures/markers); update it
  if that assumption turns out wrong during implementation.

### 5. Documentation

- `docs/test-architecture.md` — new section documenting the `@control-*`
  tagging convention and how it flows into `results.json`/SARIF.
- `vip trace --help` plus a short section in the CLI/reporting docs
  (`docs/reporting.md`) covering the traceability export.
- The new example's own `README.md` (above), generated from
  `examples/_shared/AGENTS.md` plus its own specifics, same as
  `cross_product_validation`.

## Open questions for implementation

- Whether `clients/connect.py` already exposes what's needed to read an
  audit-trail entry and attempt its deletion as a non-admin, or whether new
  client methods are required.
