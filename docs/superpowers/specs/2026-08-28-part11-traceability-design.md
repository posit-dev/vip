# Design: control tagging, traceability export, and a Part 11 example

Status: reviewed and revised 2026-08-28. Section 7 records the review findings;
sections 1-6 have been amended in place where the original claims did not
survive verification. Section 2 (evidence record additions) was promoted out of
the deferred list into the main design on the second pass.

## Context

Someone is looking for VIP to produce something close to an automated 21 CFR
Part 11 traceability matrix: a mapping from regulatory control to timestamped
test evidence. VIP already produces machine-readable per-check results
(`report/results.json`, JUnit XML, SARIF), and its Gherkin feature files are
already written as plain-language requirement statements.

What's missing is a way to attach a control ID to a scenario, a way to turn
that into an actual matrix, enough provenance on the evidence record to make a
result attributable to a specific pipeline execution, and a worked example
showing what real Part 11-flavored scenarios look like.

Be precise about what "timestamped, versioned" does and does not mean today,
because a downstream renderer will build on this wording. Before the section 2
changes land, `results.json` carries a single run-level `generated_at` and no
schema version at all: individual results have a `duration` but no start time.
So the existing evidence is run-timestamped and unversioned, and a per-control
row could not honestly claim a timestamp of its own. Section 2 is what makes
per-check timestamping and a versioned schema true rather than aspirational.

A historical/longitudinal evidence store across runs (needed for a true
deviation log) was considered and explicitly dropped for this round — VIP
already emits one timestamped file per run; whoever owns long-term archiving
can accumulate those without any new VIP storage code.

### Superseded: the PDF non-goal

The first two drafts of this spec said PDF rendering was owned by a separate
team and out of scope, and pointed at AlcoaBase as the model for VIP producing
machine-readable input that someone else renders. PR #618 changes that premise:
VIP now renders its own PDF edition of the report, natively via Quarto/Typst
(`src/vip/report_typst.py`, `report/vip-report.qmd`), and every
`quarto render` produces `_output/vip-report.pdf`.

So "a downstream PDF pipeline" is no longer hypothetical or external — it is in
this repo. That does not by itself mean the traceability matrix belongs in the
PDF, but it does mean the choice is now a live design decision rather than
something ruled out by ownership. Section 8 records it. The CSV/JSON export
remains the primary deliverable either way: a spreadsheet and an external
qualification-protocol generator are both real consumers, and neither wants a
PDF.

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

- No new PDF *engine*. PR #618 already added one; whether the matrix becomes a
  section inside it is an open decision (section 8), not a goal assumed here.
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
- Unregistered marks must be registered, not merely silenced. Each distinct
  `@control-*` tag is an unregistered mark, and pytest punishes that two
  different ways. By default it raises `PytestUnknownMarkWarning`
  (`_pytest/mark/structures.py:628`), which is a hard error under
  `-W error::pytest.PytestUnknownMarkWarning`. Under `--strict-markers` /
  `strict_markers` it does not warn at all — it calls `fail()` and aborts
  collection with "`'control-audit-trail-publish' not found in markers
  configuration option`". Verified against the pinned pytest 9.1.1.

  A `filterwarnings` ignore therefore does not solve this: it cannot touch the
  strict-markers path, which is precisely the mode a regulated customer's CI
  is most likely to enable. Instead, `plugin.py::pytest_configure` pre-scans
  the feature files it is about to collect, extracts every tag matching the
  control prefix, and registers each one via
  `config.addinivalue_line("markers", f"{tag}: compliance control tag")`.

  Verified empirically: with pre-registration, a control-tagged scenario
  collects and passes under `--strict-markers` and
  `-W error::pytest.PytestUnknownMarkWarning` together, the warnings disappear
  entirely, and the tags still arrive in `results.json`. One mechanism covers
  both failure modes, so no `filterwarnings` entry is needed at all.

  Two implementation notes. The scan must cover the same roots pytest will
  collect — `config.args` plus any `--vip-extensions` directories — rather than
  blindly walking `rootpath`, which would be wasteful in a large monorepo and
  would register controls from files that are not part of this run. And VIP
  already has a Gherkin tag parser in `gherkin.py`; reuse it rather than adding
  a second regex, keeping this consistent with the `gherkin.py` fix in the next
  bullet.
- Tag ordering in a feature file matters. `gherkin.py:52-57` derives a
  feature's `"marker"` from the first token of the first tag line in the file.
  A `@control-*` tag written before `@connect` hijacks that value, which feeds
  the report's Gherkin step lookup (`report_content.py:261` after #618,
  `report_html.py:241` before it), `generate-test-catalog.py:46`, and
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
added to the `subcommand_parsers` help map (`cli.py:1936` on main,
`cli.py:1989-1999` after #618):

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
  - Audit-log non-deletability: the audit log endpoint does not advertise a
    deletion method (`@control-record-retention`). This is read-only by
    construction — it reads the `Allow` header rather than attempting a
    delete. Proving the audit trail is immutable must never destroy an audit
    record: in a regulated deployment that record is the evidence, so the
    obvious "try to delete one and assert it fails" shape would do the exact
    harm the control exists to prevent, and would violate VIP's
    non-destructive test contract.
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
- A selftest asserting a `@control-*` tag collects cleanly under
  `--strict-markers` and under `-W error::pytest.PytestUnknownMarkWarning`, as
  separate cases and combined. Both must be covered: they are distinct code
  paths in pytest (`fail()` vs `warnings.warn`), and a fix for one does not
  imply a fix for the other.
- A selftest asserting the control tags still reach `results.json` after
  pre-registration, so a future change to the registration mechanism cannot
  silently drop the evidence it exists to preserve.

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

## 8. Interaction with PR #618 (the PDF report)

PR #618 (`feat/report-pdf`) adds a native Quarto/Typst PDF edition of the
report. Verified against the PR branch, here is exactly how it touches this
work.

### 8.1 What it does not touch

`src/vip/reporting.py`, `src/vip/plugin.py` and `src/vip/gherkin.py` do not
appear in its diff at all. Every one of section 2's evidence-record changes and
section 1's tagging changes is therefore free of textual conflict with it. #618
*consumes* those modules (`report_content.py` imports `parse_feature_file`,
`ReportData`, `TestResult`; `vip-report.qmd` imports `load_results`), so adding
fields or dict keys is a semantic change it inherits, not a collision.

### 8.2 What it moves

The report layer was restructured: content decisions extracted into a new
`src/vip/report_content.py`, with `report_html.py` reduced to markup only and a
new `report_typst.py` beside it. Two references in this spec moved:

- the Gherkin step lookup that consumes a feature's derived marker:
  `report_html.py:241` -> `report_content.py:261`
- provenance rendering: the old single `report_html.py:663-689` is now
  `provenance_rows` in `report_content.py:367-388` (data) plus a renderer in
  each backend (`report_html.py:401-413`, `report_typst.py:423-437`)

### 8.3 Where it collides

Textual conflicts to expect when this work is implemented on top of #618:
`src/vip/cli.py` (both add subcommand plumbing and constants near
`_REPORT_TEMPLATE_FILES`), `pyproject.toml` (both extend the
`force-include` block), and `AGENTS.md`. Section 4's scaffold registry moved
from `cli.py:1087` to `cli.py:1139`, and the `subcommand_parsers` help map from
`cli.py:1936` to `cli.py:1989`.

One trap worth naming: `selftests/test_cli_report.py` has a test keeping the
force-include block in sync with `_REPORT_TEMPLATE_FILES`, but it filters on
`vip/_report/`. A scaffold template maps to `vip/_scaffold/` and is silently
outside that filter, so it provides no coverage for section 4's new entry —
which is why the plan asserts the scaffold entry directly instead of assuming
the existing guard catches it.

### 8.4 The open decision: matrix as a PDF section

#618 makes it possible to render the traceability matrix into the archivable
PDF alongside the summary and per-check listing. That is attractive for this
audience — a validation lead wants one signed, archivable artifact, not a CSV
they must paste into a document — but it is a scope increase and is not
required by anything in sections 1-6.

If it is taken up, three constraints apply, all from #618 itself:

- AGENTS.md on that branch states that visual changes must land in
  `report_content` and `styles.css` in the same commit so the HTML and PDF
  editions stay identical. So the matrix cannot be a Typst-only section: it
  needs a shared content layer plus both backends.
- Every dynamic value must pass through `report_typst._lit`. A control
  description containing `#`, `*`, `_` or `$` is live Typst markup otherwise,
  and control descriptions are customer-supplied free text — this is an
  injection surface, not a cosmetic concern.
- `render_document(data, hints)` currently takes only what `results.json`
  provides. A matrix additionally needs a `controls.toml`, which the report
  pipeline has no notion of today, so either `vip-report.qmd` grows a control-
  list load with a sensible "no control list configured, skip the section"
  path, or `render_document` grows a parameter. The first is less invasive.

Recommended: ship sections 1-6 first (CSV/JSON export, which serves the
spreadsheet and external-generator consumers), and treat the PDF section as a
follow-up once the matrix data model has settled. Rendering an unstable data
model into two backends doubles the cost of every change to it.

## Open questions for implementation

- Resolved. `clients/connect.py` exposes only domain methods and no generic
  `get`/`delete`/`options`, so the example needs three new ones:
  `list_audit_logs`, `audit_log_allowed_methods`, and
  `unauthenticated_status`. They are domain methods rather than generic HTTP
  verbs on purpose — a public `get(path)` would let any future step file drive
  raw HTTP from the test layer, which is what the four-layer architecture
  exists to prevent, and returning a method set rather than a response object
  is what makes the destructive-delete shape inexpressible at the step layer.
- Whether `examples/part11_validation` should be a third example or a
  control-tagged extension of `examples/cross_product_validation` (section 4).
- Whether the `execution` block should also be surfaced in the HTML report's
  provenance rows, which today show six fields and render `None` as "not
  recorded". After #618 this is no longer one function: the row data lives in
  `report_content.py:367-388` (`provenance_rows`) and each backend renders it
  separately (`report_html.py:401-413`, `report_typst.py:423-437`), so adding a
  row means touching the shared layer and both backends together. Cheap, and it would make the same
  attribution visible to a human reader, but it widens the diff beyond the
  machine-readable path this spec is scoped to.
