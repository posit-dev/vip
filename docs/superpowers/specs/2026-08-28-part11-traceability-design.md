# Design: control tagging, traceability export, and a Part 11 example

Status: reviewed and revised 2026-08-28. Section 7 records the review findings;
sections 1-6 have been amended in place where the original claims did not
survive verification. Section 2 (evidence record additions) was promoted out of
the deferred list into the main design on the second pass.

## Context

Someone is looking for VIP to produce something close to an automated 21 CFR
Part 11 traceability matrix: a mapping from regulatory control to timestamped
test evidence. VIP already produces timestamped, versioned, machine-readable
per-check results (`report/results.json`, JUnit XML, SARIF), and its Gherkin
feature files are already written as plain-language requirement statements.
What's missing is a way to attach a control ID to a scenario, a way to turn
that into an actual matrix, enough provenance on the evidence record to make a
result attributable to a specific pipeline execution, and a worked example
showing what real Part 11-flavored scenarios look like.

PDF rendering of the final matrix is being handled by a separate team and is
explicitly out of scope here. A historical/longitudinal evidence store across
runs (needed for a true deviation log) was considered and explicitly dropped
for this round — VIP already emits one timestamped file per run; whoever owns
long-term archiving can accumulate those without any new VIP storage code.

## Goals

- Let a scenario declare which regulatory control(s) it satisfies, using a
  mechanism that's already wired into VIP's reporting pipeline.
- Make each result attributable to a specific pipeline execution and to a
  specific point in time, and make the evidence file versioned and
  tamper-evident.
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
- No cryptographic signing of the evidence record. See the honest limits of
  the checksum in section 2.4.

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
  listed as deferred work in section 7.
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
unknown marker is inert. Marker selection also still works — verified with a
negative control: `pytest -m "control-cfr-11-10-e"` selects the tagged
scenario, `-m "control-nonexistent"` deselects it.

Data flow end to end:

```
.feature @control-<slug> tag
  -> pytest-bdd marker (pytest_bdd_apply_tag)
  -> TestResult.markers in results.json
  -> vip trace joins against a supplied control list
  -> matrix (CSV/JSON)
  -> consumed by the PDF pipeline (out of scope here)
```

### 2. Evidence record: additions to `results.json`

These are producer-side changes in `src/vip/plugin.py` and the `ReportData`
model in `src/vip/reporting.py`. They are not specific to Part 11 — they make
`results.json` a defensible evidence record for any audience — but they are
what turns "a test passed somewhere, sometime" into "this check ran at this
instant, on this host, from this commit, in this pipeline execution."

All four are additive. Nothing existing is renamed or removed, so the HTML
report, JUnit and SARIF writers are unaffected.

#### 2.1 Attributability

A new nested `execution` block in the payload at `plugin.py:1299-1310`:

```json
"execution": {
  "hostname": "runner-04.example.com",
  "git": {"commit": "b134ceab...", "branch": "main", "dirty": false,
          "remote": "https://github.com/posit-dev/vip"},
  "ci": {"provider": "github", "run_id": "1234567890",
         "run_attempt": "1", "run_url": "https://github.com/o/r/actions/runs/1234567890",
         "job": "connect-smoke"}
}
```

Resolution rules, in order, each independently degrading to `null`:

- `hostname` from `platform.node()`. This is the VIP runner's host, not the
  system under test, and must be labelled that way wherever it is rendered —
  the same trap `python_version`/`platform` already fall into (section 3).
- `git` from CI environment variables first (`GITHUB_SHA`, `GITHUB_REF_NAME`),
  falling back to `git rev-parse HEAD` / `--abbrev-ref HEAD` /
  `git status --porcelain` run in the current working directory with a short
  timeout. The cwd is the right repo to interrogate: that is where `vip.toml`
  and any `--vip-extensions` directories live. VIP core's own provenance is
  already covered by `vip_version`. Document that limitation rather than
  trying to resolve a SHA per extension directory.
- `ci` from environment variables only, never a subprocess. GitHub Actions
  (`GITHUB_RUN_ID` + `GITHUB_SERVER_URL` + `GITHUB_REPOSITORY` composed into
  `run_url`), GitLab (`CI_JOB_URL`), Jenkins (`BUILD_URL`). Unknown CI, or no
  CI, yields `null` rather than a guess.

Three constraints on the implementation:

- Never fail a run. Every probe is wrapped; a missing `git` binary, a detached
  worktree, a non-repo cwd, or a subprocess timeout produces `null`, never an
  exception and never a warning that would pollute a clean run.
- Redact userinfo from the remote URL. CI checkouts routinely rewrite the
  origin to embed a credential (`https://x-access-token:ghs_...@github.com/...`).
  `results.json` is an uploaded CI artifact — `plugin.py:1196-1201` already
  strips absolute paths for exactly this reason — so the remote is parsed and
  any userinfo component dropped before it is recorded. A remote that cannot
  be parsed is recorded as `null`, not passed through raw.
- Provide an opt-out. `--vip-no-attribution` omits the whole `execution` block.
  Hostname and repository identity are modest but real infrastructure
  disclosure, and some customers will not want them in an artifact that leaves
  their network. Default is on, because for the use case driving this work
  these fields are the point.

#### 2.2 Per-test timestamps

Each entry in `results` gains `started_at` and `finished_at`, UTC ISO 8601,
derived from `report.start` and `report.stop` at `plugin.py:1203-1216`.

Verified empirically: `report.start`/`report.stop` are epoch floats present on
`TestReport`, and they survive xdist's worker-to-controller serialization —
confirmed under both `-n 0` and `-n 2`, which matters because the controller is
the only process that writes the report (`plugin.py:1173-1176`).

One precision point to document rather than gloss: the collection site fires
for `report.when == "call"`, or for a setup-phase skip
(`plugin.py:1185`). So `started_at` is when the check itself began, excluding
fixture setup, except for setup-skips where it is the setup start. That is the
right semantic for "when was this control exercised", but it is not the same as
"when did this test item begin", and a qualification document that says the
latter would be wrong. Both fields fall back to `null` via `getattr` if a
future pytest drops the attributes.

This is what makes the phrase "timestamped test evidence" true at per-check
granularity rather than only at run granularity.

#### 2.3 Schema version

A `schema_version` string at the top of the payload, introduced as `"1.0"`
together with these additions.

Semantics: bump the minor for additive changes (a new field), bump the major
for a removal, a rename, or a change in the meaning of an existing field. A
consumer should accept an unknown minor and refuse an unknown major. The
historical unversioned shape is "pre-1.0" — a consumer seeing no
`schema_version` at all knows it predates this work.

`vip trace` implements exactly that policy: unknown minor proceeds, unknown
major is a hard error naming both versions. A downstream PDF generator gets a
stable contract to code against instead of shape-sniffing.

#### 2.4 Tamper-evidence

The plugin writes a `results.json.sha256` sidecar immediately after
`p.write_text(...)` at `plugin.py:1315`, in the standard
`<hex>  results.json` format so `shasum -c` verifies it directly. It is written
unconditionally, not gated on `--vip-format`, because the checksum is a
property of the evidence file rather than an output format.

The digest covers the exact bytes written. Note that `results.json` is written
without a trailing newline while `failures.json` adds one
(`plugin.py:1315` vs `:1344`) — hash the bytes, not a re-serialization.

`vip trace` then recomputes the digest of the file it reads, records it in the
matrix provenance block as `results_sha256`, and — if the sidecar is present —
compares. A mismatch is a hard error, not a warning. A checksum mismatch on a
compliance artifact is precisely the condition that must not be papered over.

The honest limit, which belongs in the docs and not just here: this is
tamper-evidence within a trusted pipeline, not tamper-proofing. Anyone able to
edit `results.json` can also regenerate the sidecar. It detects accidental
corruption, truncated uploads, and casual editing; it does not resist a
motivated forger. Real integrity requires a signature under a key the editor
does not hold, or write-once storage — deliberately out of scope (see
Non-goals). Under ALCOA+ this supports "original" and "accurate" as a detection
aid; claiming more than that would be the same category of overreach section
7.1 warns about.

### 3. Traceability export (`vip trace`)

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
- each match's `started_at` / `finished_at` (section 2.2)
- `concise_error` / `skip_reason` on non-passing matches, so the matrix
  carries the actual evidence and not just a verdict

Coverage outcomes are three-valued, not two. A control with zero matching
scenarios is a coverage gap; a control declared `verification: manual` or
`verification: procedural` in the control list is reported as "not verifiable
by automated test" and is not counted as a gap. Conflating the two is the
single most misleading thing this export could do — see section 7.

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
qualification artifact. All of it comes from `results.json`:

- `generated_at`, `vip_version`, `deployment_name`, `exit_status`,
  `schema_version`
- the full `execution` block from section 2.1 — hostname, git commit, CI run
  URL
- `results_sha256` and the sidecar verification result from section 2.4
- per-product `url` and detected `version` from the `products` table
- `basic_mode` — surfaced prominently, because a matrix built from a
  `vip verify --basic` run silently omits every `@slow` scenario and would
  otherwise assert coverage that was never exercised

One provenance caveat to render honestly rather than paper over:
`python_version`, `platform`, and `execution.hostname` all describe the VIP
runner, not the system under test, and must be labelled that way. The system
under test is identified by the `products` table.

#### Determinism

"Deterministic" here means the export is a pure function of its inputs: the
same `results.json` and `controls.toml` produce byte-identical output. It does
not mean two separate verification runs produce identical matrices — they
cannot, and should not, because timestamps and the run's identity are the
evidence.

Two things are needed for that. `results` in `results.json` is in xdist arrival
order (default `addopts = "-n auto --dist loadgroup"`), so the export sorts
deterministically: by `control_id`, then by nodeid within a control. And
per-test `duration` is omitted from matrix rows — it is performance noise that
varies run to run without carrying evidentiary value, unlike `started_at`,
which is retained precisely because it does.

#### CLI surface

New subcommand in `src/vip/cli.py`, following the existing argparse +
`set_defaults(func=...)` pattern used by the nine current subcommands, and
added to the `subcommand_parsers` help map at `cli.py:1936`:

```
vip trace --results report/results.json --controls path/to/controls.toml \
    [--tag-prefix control-] [--format csv|json] [--output path]
```

Output defaults to stdout as CSV (the natural input to a downstream PDF/
qualification protocol generator or a spreadsheet); JSON is available for
programmatic consumption and carries the full provenance block. The matrix
output carries its own `schema_version`, versioned independently of
`results.json`.

### 4. New example: `examples/part11_validation/`

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
  test set, and carries the scope disclaimer from section 7. Customers replace
  and extend `controls.toml` and add their own scenarios for their actual
  regulatory mapping. Documents the `@control-*` convention and points at
  `vip trace`.

### 5. Testing

For the export (section 3):

- `selftests/` coverage for `build_traceability_matrix`: full coverage, a
  coverage gap, a not-automatable control, an unrecognized-tag warning, one
  control satisfied by multiple scenarios, and stable sort order across two
  differently-ordered input result lists.
- A selftest exercising the `vip trace` CLI end-to-end against a fixture
  `results.json` + `controls.toml`, checking both CSV and JSON output.
- Byte-identical output across two invocations on the same input, asserting
  the determinism claim rather than assuming it.

For the tagging convention (section 1):

- A selftest asserting a `@control-*` tag does not hijack `gherkin.py`'s
  derived feature marker.
- A selftest asserting a `@control-*` tag raises no warning under the plugin's
  filter — run it under `-W error::pytest.PytestUnknownMarkWarning`.

For the evidence record (section 2), all via the `pytester` fixture so a real
subprocess run produces a real `results.json`:

- `started_at`/`finished_at` present, ISO 8601, UTC, and ordered
  `started_at <= finished_at`; present for a setup-phase skip as well as a
  passing call.
- The `execution` block degrades to `null` fields rather than raising when
  `git` is unavailable, when cwd is not a repo, and when no CI env vars are
  set — three separate cases.
- A remote URL carrying userinfo is redacted. This is a secret-leak
  regression test, so assert the token string is absent from the whole file,
  not merely that the remote field looks clean.
- `--vip-no-attribution` omits the block entirely.
- The `.sha256` sidecar matches the bytes actually on disk, and `vip trace`
  raises on a deliberately corrupted `results.json`.
- `schema_version` is present; `vip trace` accepts an unknown minor and
  refuses an unknown major.
- A pre-1.0 `results.json` — no `schema_version`, no `started_at`, no
  `execution` block — still loads and traces, with the absent fields rendered
  as null rather than raising. This is the common case in practice, not the
  unknown-major case: anyone with an archived results file from before this
  work lands hits it. `load_results` (`reporting.py:176-190`) already uses
  `.get()` with defaults for every optional field, so the new fields must
  follow that existing pattern and carry dataclass defaults rather than being
  required constructor arguments.

Plus: `examples/part11_validation` collected via `--collect-only` in CI, the
same way `cross_product_validation` already is; and
`selftests/test_scaffold_agents_md.py` verified for whether the new example
needs an inventory update (it should not — it reuses existing fixtures and
markers — but confirm rather than assume).

### 6. Documentation

- `docs/test-architecture.md` — new section documenting the `@control-*`
  tagging convention, the tag-ordering rule, and how it flows into
  `results.json`.
- `docs/reporting.md` — currently documents none of `results.json`, `junit.xml`,
  or `results.sarif`. Document the machine-readable outputs there first,
  including the section 2 additions and the `schema_version` compatibility
  policy, then add the traceability export on top; `vip trace --help` alone is
  not discovery. The tamper-evidence limitation from section 2.4 goes here in
  plain language, not just in this spec.
- The new example's own `README.md` (above), generated from
  `examples/_shared/AGENTS.md` plus its own specifics, same as
  `cross_product_validation`.

## 7. Review findings

### 7.1 Scope: what an automated matrix can and cannot claim

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

Consequences, all folded into sections 3 and 4 above:

- The control list carries `verification` and `responsibility` fields.
- "Not verifiable by automated test" is a distinct outcome from "coverage gap".
- The example ships a procedural and a customer-responsibility control so the
  distinction is visible in the worked example.
- The example README states that a fully green matrix is evidence for the
  subset of controls a customer chose to automate, and is not a Part 11
  compliance attestation.

### 7.2 Verified as stated

Hyphenated control tags reach `results.json` unfiltered; auto-skip is
unaffected; `pytest -m` selection works (confirmed with a negative control);
`reporting.py` already imports `tomllib`; the `_SCAFFOLD_TEMPLATES` registry
takes a new template in one dict entry; `cli.py` uses plain argparse
throughout. `TestResult` already carries `scenario_title`,
`feature_description`, `status`, `longrepr`, `concise_error`, `skip_reason`,
and `na_version` — enough evidence per row without a schema change.
`report.start`/`report.stop` exist and survive xdist serialization, which is
what makes section 2.2 cheap.

### 7.3 Corrected in place

SARIF/JUnit do not carry markers (section 1); unregistered marks warn and are
fatal under strict warning settings, so a small plugin change is required
(section 1); `gherkin.py` derives a feature's marker from the first tag and can
be hijacked (section 1); `results.json` is not deterministically ordered
(section 3); the captured `python_version`/`platform` describe the runner, not
the system under test (section 3).

### 7.4 Promoted into the design

Four items from the first review's deferred list were promoted into section 2
on the second pass: attributability, per-test timestamps, schema version, and
tamper-evidence. They share a rationale — the requester asked for evidence
sourced from CI/CD, and without them a result cannot be tied to a specific
pipeline execution, a specific instant, a stable contract, or a verifiable set
of bytes.

### 7.5 Still deferred, considered and named

Not scope creep — recorded so a later round doesn't rediscover them:

- Step-level evidence. Real RTMs cite a protocol step ("OQ, Test Case 3,
  Step 52"). VIP captures nothing below the scenario: no
  `pytest_bdd_after_step` / `pytest_bdd_step_error` hooks are implemented.
  Gherkin Given/When/Then steps are the natural analogue, and pytest-bdd ships
  a step-level emitter (`pytest_bdd/cucumber_json.py`) that VIP does not enable.
  This is the largest remaining gap against how qualification protocols are
  actually written.
- Captured stdout/log as evidence. `longrepr` is nulled for skips and no
  `capstdout`/`caplog` is retained, so a failure row carries a traceback but no
  surrounding output.
- Deviation log. A structured failure record (expected vs actual, control
  impacted, disposition) is what regulated customers mean by a deviation log.
  This needs cross-run history, which stays a non-goal for now.
- Cryptographic signing of the evidence record, per section 2.4.
- Runtime versions on the system under test (R and Python interpreters
  available on Workbench/Connect) as part of the provenance block. VIP already
  has `expected_r_versions` / `expected_python_versions` config, so the
  observed values are within reach.
- SARIF `properties.tags` for control tags, if anything downstream wants to
  read the mapping from SARIF rather than JSON.

### 7.6 On the cited references

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
  control-tagged extension of `examples/cross_product_validation` (section 4).
- Whether the `execution` block should also be surfaced in the HTML report's
  provenance table (`report_html.py:663-689`), which today shows six fields and
  renders `None` as "not recorded". Cheap, and it would make the same
  attribution visible to a human reader, but it widens the diff beyond the
  machine-readable path this spec is scoped to.
