# Part 11 validation example

A worked example of mapping regulatory controls to automated tests, and
exporting the result as a traceability matrix with `vip trace`.

`VALIDATION-PACKAGE.md`, next to this file, is the wider context: which
documents in a GxP validation package VIP produces, which ones you author, and
which ones no test tool can produce. Read it before deciding what this example
is worth in your process.

## What this is not

This is a template, not a certified Part 11 test set. A fully green matrix is
evidence for the subset of controls you chose to automate. It is not an
attestation of 21 CFR Part 11 compliance, and nobody should present it as one.

Most of Part 11 cannot be evidenced by an automated test against Posit Team.
Roughly six clauses are genuinely testable against a deployment -- 11.10(a),
11.10(d), 11.10(e), 11.10(g), 11.30, and partly 11.10(b). Several more are
shared with your own procedures. The rest are either procedural (11.10(i),
11.10(j)) or properties of the application you build on top of Posit Team.

In particular, Posit Team does not implement electronic signatures. Clause
11.50 (signature manifestations), 11.70 (signature/record linking) and all of
subpart C (11.100, 11.200, 11.300) are satisfied by your application and your
SOPs, not by Connect, Workbench or Package Manager. `controls.toml` includes
two such controls so you can see how a non-automatable control appears in the
matrix: as "not verifiable by automated test", which is deliberately distinct
from "coverage gap".

A green matrix is also not evidence that the tests ran. VIP skips every scenario
belonging to a product you have not configured, and a skipped scenario still
counts as covering its control. Run this against an unconfigured deployment and
you get a matrix reading "covered, 0 gaps" in which nothing was checked. `vip
trace` warns when that happens and the JSON summary reports
`covered_not_executed` separately, but the CSV `coverage` column alone will not
tell you. Read the `status` column with it.

## How it works

A scenario declares the control it satisfies with a Gherkin tag:

```gherkin
@control-audit-trail-publish
Scenario: Publishing content is recorded with an actor and a timestamp
```

A control tag can sit before or after the product tag without changing anything
-- VIP derives the feature's marker from the first non-control tag it finds,
skipping `@control-<slug>` entirely. But the product tag (`@connect`,
`@workbench`) should still be the first tag that is not a control tag, because
only control tags are skipped: `@slow @connect` derives the marker `slow`. The
derived marker feeds the HTML report's per-feature grouping and the generated
test catalog and feature matrix, while the product markers themselves
separately drive auto-skip when a product is not configured.

`controls.toml` names each control and carries whatever metadata your
regulatory mapping uses. Only `description` is required, and every field must be
a quoted string -- TOML would otherwise read `reference = 2024-01-01` as a date,
which the JSON export cannot serialise.

Control ids become pytest marker names, so use only letters, digits, `-`, `.`
and `_`. Write `11-10-a`, not `11.10(a)`: a `:` or `(` truncates the marker name
pytest registers and breaks collection under `--strict-markers`.

## Running it

```bash
vip verify --config vip.toml --extensions ./21CFR_part11_validation
vip trace --results report/results.json --controls ./21CFR_part11_validation/controls.toml
```

Add `--format json` for a machine-readable matrix carrying the full provenance
block, or `--output matrix.csv` to write to a file.

## Extending it

Replace `controls.toml` with your own mapping and tag your own scenarios. See
`security/test_auth_policy.py` in the VIP source for a fuller reference
implementation of access-control testing, and
`examples/cross_product_validation/` for the broader GxP starting point.
