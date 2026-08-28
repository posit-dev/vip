# Design: control tagging, traceability export, and a Part 11 example

Status: reviewed 2026-08-28. Section 6 records the review findings; sections 1-5
have been amended in place where the original claims did not survive verification.

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
  pytest marker via `getattr(pytest.mark, tag)`
  (`pytest_bdd/plugin.py:136-139`). This works with hyphens since it's dynamic
  attribute access, and pytest-bdd 8.1.0 does no tag-name validation. Feature-
  and rule-level tags are applied too, not just scenario-level ones
  (`pytest_bdd/scenario.py:316-319`).
- VIP's plugin captures every marker on a test, unfiltered, in
  `pytest_runtest_makereport` (`plugin.py:1073-1087`), stashes it on the report
  for xdist transport, and reads it back in `pytest_runtest_logreport`
  (`plugin.py:1211`) into `TestResult.markers`. Verified empirically: a
  scenario tagged `@connect @control-cfr-11-10-e @control-audit-trail-publish`
  yields `markers: ["connect", "control-cfr-11-10-e",
  "control-audit-trail-publish", "xdist_group"]` in `results.json`.

Three corrections to the original draft of this section:

- SARIF and JUnit do not carry markers. `write_sarif` sets `ruleId` to the
  nodeid and `logicalLocations[].name` to `"<category> / <check>"`
  (`reporting.py:313,317`); `write_junit_xml` emits only `name`/`classname`/
  `time` (`reporting.py:227-274`). The string `markers` appears in neither.
  Control tags therefore flow through `results.json` only, which is the input
  `vip trace` reads — so this costs nothing here, but the claim that "no
  reporting schema change is needed" is only true for the JSON path. Adding
  control tags to SARIF (as `properties.tags`, which the format supports) is
  listed as deferred work in section 6.
- Unregistered marks warn. Each distinct `@control-*` tag raises a
  `PytestUnknownMarkWarning` (`_pytest/mark/structures.py:628`). Nothing in
  VIP escalates it today, so a run merely gets a noisy warnings summary — but
  under `-W error::pytest.PytestUnknownMarkWarning` it is a hard collection
  error, which a regulated customer running strict CI is plausibly doing.
  Dynamic slugs cannot be pre-registered by name, so `plugin.py::pytest_configure`
  gains one `filterwarnings` line ignoring `PytestUnknownMarkWarning` for marks
  matching the configured prefix, alongside the seven `ignore:` entries already
  at `plugin.py:156-173`. This is a small plugin change, not zero.
- Tag ordering in a feature file matters. `gherkin.py:52-57` derives a
  feature's `"marker"` from the first token of the first tag line in the file.
  A `@control-*` tag written before `@connect` hijacks that value, which feeds
  the report cards (`report_html.py:241`), `generate-test-catalog.py:46`, and
  `generate-feature-matrix.py:142`. Fix `gherkin.py` to skip tags matching the
  control prefix when deriving the marker, rather than relying on authors to
  order tags correctly.

Auto-skip is unaffected: `_should_deselect_for_product` and `_requires_auth`
(`plugin.py:687-755`) use exact `get_closest_marker` lookups, so an extra
unknown marker is inert. Marker selection also still works —
`pytest -m "control-cfr-11-10-e"` selects correctly despite the hyphens.

Data flow end to end:

```
.feature @control-<slug> tag
  -> pytest-bdd marker (pytest_bdd_apply_tag)
  -> TestResult.markers in results.json
  -> vip trace joins against a supplied control list
  -> matrix (CSV/JSON)
  -> consumed by the PDF pipeline (out of scope here)
```

### 2. Traceability export (`vip trace`)

A new pure function in `src/vip/reporting.py`:

```python
def build_traceability_matrix(
    data: ReportData,
    controls: dict[str, ControlSpec],
    tag_prefix: str = "control-",
) -> TraceabilityMatrix:
    ...
```

For each control in the supplied `controls` mapping, it scans `data.results`
for any result whose `markers` includes `f"{tag_prefix}{control_id}"` and
produces one `ControlEntry`:

- `control_id` plus every field carried on the `ControlSpec` (below)
- the matching scenario title(s) and nodeid(s)
- each match's `status` (reusing `TestResult.status`, so an N/A-by-version
  skip renders distinctly from an ordinary skip)
- `concise_error` / `skip_reason` on non-passing matches, so the matrix
  carries the actual evidence and not just a verdict

Coverage outcomes are three-valued, not two. A control with zero matching
scenarios is a coverage gap; a control declared `verification: manual` or
`verification: procedural` in the control list is reported as "not verifiable
by automated test" and is not counted as a gap. Conflating the two is the
single most misleading thing this export could do — see section 6.

A `control-*` tag found in the results that is not present in the supplied
control list is reported as an "unrecognized control tag" warning — this
catches typos (`@control-cfr-11-10e` vs `@control-cfr-11-10-e`) at export time
instead of silently losing coverage.

#### Control list format

`controls.toml` uses a table per control rather than flat `id = "description"`
string pairs, so it can carry the columns real qualification matrices use
without a breaking format change later:

```toml
[controls.cfr-11-10-e]
description = "Secure, computer-generated, time-stamped audit trails"
reference = "21 CFR 11.10(e)"
risk = "high"
verification = "automated"          # automated | manual | procedural
responsibility = "shared"           # posit | customer | shared
notes = "Retention duration is a customer configuration decision."
```

`description` is the only required key; the rest are optional and pass through
to the output verbatim. VIP does not interpret `risk`, `reference`, or
`responsibility` — it stays regulation-agnostic and just carries the customer's
own taxonomy through to the matrix. Loaded with `tomllib`, already imported at
`reporting.py:12-15`.

#### Provenance header

The export carries a provenance block, because a matrix without one is not a
qualification artifact. Everything below already exists in `results.json`
(`plugin.py:1273-1310`) and just needs forwarding:

- `generated_at`, `vip_version`, `deployment_name`, `exit_status`
- per-product `url` and detected `version` from the `products` table
- `basic_mode` — surfaced prominently, because a matrix built from a
  `vip verify --basic` run silently omits every `@slow` scenario and would
  otherwise assert coverage that was never exercised

Two provenance caveats to render honestly rather than paper over:
`python_version` and `platform` are the VIP runner's interpreter and OS, not
the system under test, and must be labelled that way. Hostname, git SHA of the
test suite, and CI run URL are not captured at all today — see section 6.

#### Determinism

`results.json` is not reproducible byte-for-byte: `results` is in xdist
arrival order (default `addopts = "-n auto --dist loadgroup"`), and
`generated_at`, `run_duration_seconds`, and per-test `duration` change every
run. The export therefore sorts deterministically — by `control_id`, then by
nodeid within a control — and omits durations from the matrix rows. Two runs
against the same deployment with the same results then produce diffable
output, which is what a downstream deterministic-PDF step needs.

CLI surface (new subcommand in `src/vip/cli.py`, following the existing
argparse + `set_defaults(func=...)` pattern used by the nine current
subcommands, and added to the `subcommand_parsers` help map at `cli.py:1936`):

```
vip trace --results report/results.json --controls path/to/controls.toml \
    [--tag-prefix control-] [--format csv|json] [--output path]
```

Output defaults to stdout as CSV (the natural input to a downstream PDF/
qualification protocol generator or a spreadsheet); JSON is available for
programmatic consumption and carries the full provenance block.

### 3. New example: `examples/part11_validation/`

Mirrors the existing `examples/cross_product_validation/` structure and the
four-layer architecture, registered in `_SCAFFOLD_TEMPLATES`
(`cli.py:1084-1097`, one dict entry mapping `part11-validation` ->
`examples/part11_validation`) so it's reachable via
`vip scaffold --template part11-validation --output DIR`.

Note that `examples/cross_product_validation/` is already described as the GxP
example (`docs/test-architecture.md:333`) and its feature narrative already
says "So that GxP and other compliance requirements are continuously met".
Decide during implementation whether this is a third example or a control-tagged
extension of that one; if it stays separate, both READMEs must cross-link so
customers don't have to guess which is the GxP starting point.

- `test_part11_validation.feature` — a small, illustrative scenario set, each
  tagged with both a product marker (`@connect`/`@workbench`) and a
  `@control-*` tag, with the product tag written first (see the `gherkin.py`
  footgun in section 1):
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
  exist). Every `@scenario` function also carries a literal
  `@pytest.mark.connect` / `@pytest.mark.workbench` decorator — per CLAUDE.md,
  feature-level Gherkin tags alone do not drive auto-skip in extension
  directories.
- `conftest.py` — override-fixture pattern matching the existing example
  (e.g. which privileged action to exercise).
- `controls.toml` — a sample control list demonstrating the format `vip trace`
  expects. It includes at least one `verification = "procedural"` entry and one
  `responsibility = "customer"` entry, so the worked example shows the
  not-automatable path and not only the happy path.
- `README.md` — states plainly that this is a template, not a certified Part 11
  test set, and carries the scope disclaimer from section 6. Customers replace
  and extend `controls.toml` and add their own scenarios for their actual
  regulatory mapping. Documents the `@control-*` convention and points at
  `vip trace`.

### 4. Testing

- `selftests/` coverage for `build_traceability_matrix`: full coverage, a
  coverage gap, a not-automatable control, an unrecognized-tag warning, one
  control satisfied by multiple scenarios, and stable sort order across two
  differently-ordered input result lists.
- A selftest exercising the `vip trace` CLI end-to-end against a fixture
  `results.json` + `controls.toml`, checking both CSV and JSON output.
- A selftest asserting a `@control-*` tag does not hijack
  `gherkin.py`'s derived feature marker.
- A selftest asserting a `@control-*` tag raises no warning under the plugin's
  filter — run it under `-W error::pytest.PytestUnknownMarkWarning`.
- `examples/part11_validation` collected via `--collect-only` in CI, the same
  way `cross_product_validation` already is.
- `selftests/test_scaffold_agents_md.py` — verify the new example doesn't
  need an inventory update (it reuses existing fixtures/markers); update it
  if that assumption turns out wrong during implementation.

### 5. Documentation

- `docs/test-architecture.md` — new section documenting the `@control-*`
  tagging convention, the tag-ordering rule, and how it flows into
  `results.json`.
- `docs/reporting.md` — currently documents none of `results.json`, `junit.xml`,
  or `results.sarif`. Document the machine-readable outputs there first, then
  add the traceability export on top; `vip trace --help` alone is not discovery.
- The new example's own `README.md` (above), generated from
  `examples/_shared/AGENTS.md` plus its own specifics, same as
  `cross_product_validation`.

## 6. Review findings

### 6.1 Scope: what an automated matrix can and cannot claim

This is the most important finding and it changes what the export must be able
to express.

Published vendor Part 11 matrices (Beckman QbD1200, Microtrac) use five
columns: CFR section, regulation text, compliance yes/no, vendor
implementation, and customer responsibilities. That last column exists because
most of Part 11 is a shared or wholly-customer obligation.

Mapping the clauses against what VIP can assert about a Posit Team deployment:
roughly six are genuinely testable (11.10(a) validation, 11.10(d) access
limits, 11.10(e) audit trails, 11.10(g) authority checks, 11.30 open-system
transport controls, and partially 11.10(b) record copies); about five are
shared; and the remainder are procedural (11.10(i), 11.10(j)) or are properties
of the customer's application rather than of Posit Team.

Critically, that remainder includes every clause the requester named first.
Posit Team does not implement electronic signatures, so 11.50 (signature
manifestations), 11.70 (signature/record linking), and all of subpart C
(11.100/11.200/11.300) cannot be evidenced by a test against Connect,
Workbench, or Package Manager. VIP's TOTP support proves an MFA login path,
which is not the same thing as a compliant signing ceremony and must not be
tagged as though it were.

Consequences, all folded into sections 2 and 3 above:

- The control list carries `verification` and `responsibility` fields.
- "Not verifiable by automated test" is a distinct outcome from "coverage gap".
- The example ships a procedural and a customer-responsibility control so the
  distinction is visible in the worked example.
- The example README states that a fully green matrix is evidence for the
  subset of controls a customer chose to automate, and is not a Part 11
  compliance attestation.

### 6.2 Verified as stated

Hyphenated control tags reach `results.json` unfiltered; auto-skip is
unaffected; `pytest -m` selection works; `reporting.py` already imports
`tomllib`; the `_SCAFFOLD_TEMPLATES` registry takes a new template in one dict
entry; `cli.py` uses plain argparse throughout. `TestResult` already carries
`scenario_title`, `feature_description`, `status`, `longrepr`,
`concise_error`, `skip_reason`, and `na_version` — enough evidence per row
without a schema change.

### 6.3 Corrected in place

SARIF/JUnit do not carry markers (section 1); unregistered marks warn and are
fatal under strict warning settings, so a small plugin change is required
(section 1); `gherkin.py` derives a feature's marker from the first tag and can
be hijacked (section 1); `results.json` is not deterministically ordered
(section 2); the captured `python_version`/`platform` describe the runner, not
the system under test (section 2).

### 6.4 Deferred, considered and named

Not scope creep — recorded so a later round doesn't rediscover them:

- Attributability. `results.json` has no hostname, no git SHA for the test
  suite, and no CI run URL. For evidence sourced from CI/CD — which is exactly
  what was asked for — those are the fields that make a result attributable to
  a specific pipeline execution. Adding them is a few lines in
  `plugin.py:1298-1310` and is the highest-value follow-up.
- Per-test timestamps. Only run-level `generated_at` exists; individual results
  carry `duration` but no start time. "Timestamped test outputs" is currently
  true at run granularity only.
- Schema version. `results.json` has no version field, and a downstream PDF
  generator consuming it will want one.
- Step-level evidence. Real RTMs cite a protocol step ("OQ, Test Case 3,
  Step 52"). VIP captures nothing below the scenario: no
  `pytest_bdd_after_step` / `pytest_bdd_step_error` hooks are implemented.
  Gherkin Given/When/Then steps are the natural analogue, and pytest-bdd ships
  a step-level emitter (`pytest_bdd/cucumber_json.py`) that VIP does not enable.
- Captured stdout/log as evidence. `longrepr` is nulled for skips and no
  `capstdout`/`caplog` is retained, so a failure row carries a traceback but no
  surrounding output.
- Deviation log. A structured failure record (expected vs actual, control
  impacted, disposition) is what regulated customers mean by a deviation log.
  This needs cross-run history, which stays a non-goal for now.
- Tamper-evidence. No checksum of `results.json` is emitted. A SHA-256 in the
  matrix provenance block is cheap and directly serves the ALCOA+ "original"
  and "accurate" attributes.
- SARIF `properties.tags` for control tags, if anything downstream wants to
  read the mapping from SARIF rather than JSON.

### 6.5 On the cited references

The "GxP AI Validation framework" could not be located as a GitHub repository;
the search surfaces vendor and consultancy material rather than open source,
matching the requester's own inability to find an example.

AlcoaBase resolves to `hapi-ds/ALC` — a single-star, early-stage project, so
useful as a structural reference rather than as an established standard. Two
things in it are worth borrowing and are reflected above: its
`Requirements/RiskBasedTesting.md` presents a final traceability matrix as
`URS ID | Risk | Test Case ID | Status`, which is why `risk` and `reference`
became control-list fields; and its `docs/test-protocols/*.md` show the
per-step protocol shape (action, command, expected result, actual result,
status, tester, timestamp) that motivates the deferred step-level item.

It also validates the PDF non-goal: AlcoaBase is itself the deterministic-PDF
and document-management layer. The right division of labour is for VIP to
produce clean, deterministic, well-provenanced machine-readable input and for
that layer to render it.

## Open questions for implementation

- Whether `clients/connect.py` already exposes what's needed to read an
  audit-trail entry and attempt its deletion as a non-admin, or whether new
  client methods are required.
- Whether `examples/part11_validation` should be a third example or a
  control-tagged extension of `examples/cross_product_validation` (section 3).
