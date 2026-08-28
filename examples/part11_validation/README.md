# Part 11 validation example

A worked example of mapping regulatory controls to automated tests, and
exporting the result as a traceability matrix with `vip trace`.

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

## How it works

A scenario declares the control it satisfies with a Gherkin tag:

```gherkin
@control-audit-trail-publish
Scenario: Publishing content is recorded with an actor and a timestamp
```

Write the product tag (`@connect`, `@workbench`) first -- VIP derives the
feature's marker from the first non-control tag, and that value feeds the HTML
report and the generated test catalog.

`controls.toml` names each control and carries whatever metadata your
regulatory mapping uses. Only `description` is required.

## Running it

```bash
vip verify --config vip.toml --extensions ./part11_validation
vip trace --results report/results.json --controls ./part11_validation/controls.toml
```

Add `--format json` for a machine-readable matrix carrying the full provenance
block, or `--output matrix.csv` to write to a file.

## Extending it

Replace `controls.toml` with your own mapping and tag your own scenarios. See
`security/test_auth_policy.py` in the VIP source for a fuller reference
implementation of access-control testing, and
`examples/cross_product_validation/` for the broader GxP starting point.
