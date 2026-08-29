# VIP and a GxP validation package

A regulated customer asking "can VIP validate our Posit deployment" is usually
asking a narrower question than it sounds: which of the documents in their
validation package can this tool produce, and which must they still author.

This page answers that plainly. It exists so nobody has to infer the boundary
from a feature list, and so a green report is never mistaken for something it
is not.

## The short version

VIP produces executed test evidence and the traceability that links it to your
controls. It does not produce the qualification protocols that evidence goes
into, and it cannot produce the documents that describe your organisation,
your risk posture, or your procedures.

A validation package is mostly writing. VIP automates the part that is mostly
running.

## What VIP supplies

Executed test evidence, at scenario granularity. Every check records its
outcome, a start and finish timestamp, and the deployment it ran against. This
is the raw material an Operational Qualification is built from: evidence that a
specific function behaved as specified, on a specific system, at a specific
time.

A requirement-to-evidence traceability matrix. You author `controls.toml` with
your own control list. Scenarios declare which control they verify with an
`@control-<slug>` Gherkin tag. `vip trace` joins the two and exports CSV or
JSON, and `vip report --controls` renders the same content into the HTML report
and the archivable PDF. The join is the deliverable: it is what lets a reviewer
go from a control to the check that evidences it without a spreadsheet
maintained by hand.

Execution provenance. Each results file records which host ran the tests, which
git commit and branch they came from, whether that tree was dirty, and which CI
job produced them. This is what makes a result attributable to a pipeline
execution rather than to an anonymous green tick.

Tamper-evidence. A `results.json.sha256` sidecar detects corruption in transit,
a truncated upload, or a file edited after the fact and not re-checksummed.

Read that last one precisely. It is tamper-evidence within a trusted pipeline,
not tamper-proofing and not an immutable audit trail. Anyone who can edit the
results file can regenerate the sidecar to match. It catches accidents, which
is the failure that actually happens to archived CI artifacts. It does not
resist a motivated forger, and it must never be presented as though it does.

## What you author

These are yours. No test tool produces them, because each one describes your
organisation rather than the software.

A User Requirements Specification, stating what the system must do in your
process. VIP consumes the result of this work as a control list. It cannot
derive one.

A Validation Master Plan, covering your validation policy, the organisational
structure and responsibilities, the inventory of systems in scope, and the
timelines and training that go with them.

Risk assessments. Which controls matter, how badly, and why. `controls.toml`
carries a `risk` field and VIP passes it through untouched, without
interpreting it. Deciding the value is the assessment.

The qualification protocols themselves. Installation, Operational and
Performance Qualification documents are structured, pre-approved, signed
records. VIP supplies evidence that can go inside an OQ. It does not write the
protocol, define the acceptance criteria, or carry the approval signatures.

Standard Operating Procedures, training records, and the change control and
deviation records that surround a validated system.

The validation summary report, and the Quality review and approval that closes
the exercise.

## What nothing can automate

Some controls have no automated test by their nature, and a matrix that
reported them as coverage gaps would train reviewers to ignore every real gap
sitting next to them. This is why `verification` exists in `controls.toml` and
why `not_automatable` is a distinct coverage value rather than folded into
`gap`.

Procedural controls, such as whether personnel have the training and experience
to perform their tasks. The evidence is a training record in your quality
system.

Controls satisfied by a physical or organisational process rather than by
software behaviour.

Controls that are properties of the application you build on top of Posit Team,
not of the platform. Posit Team does not implement electronic signatures, so
21 CFR Part 11 clauses 11.50 and 11.70, and all of subpart C, are satisfied by
your application and your procedures. No amount of testing Connect, Workbench
or Package Manager will evidence them.

## The gap worth knowing about

VIP captures nothing below the scenario. A qualification protocol is written as
numbered steps, each with an expected result and an observed result, and a
reviewer follows it step by step. VIP records that a scenario passed, not that
step 3 of 7 produced the expected value.

This is the largest remaining distance between VIP's output and a document
shaped like an executed protocol. If your process requires step-level evidence,
plan to record it another way for now.

Two smaller absences worth stating: there is no cross-run deviation log, which
would need history VIP does not keep, and there is no cryptographic signing of
results.

## Reading a green report

A fully green matrix evidences the controls you chose to automate, on the
deployment you pointed it at, at the time it ran. That is all it claims.

Three specific ways it can mislead if read carelessly:

Coverage is not execution. A control counts as covered when a scenario is
tagged for it. VIP skips every scenario belonging to a product that is not
configured, so a run against an unconfigured deployment produces a matrix that
is fully covered and entirely unevidenced. The report shows those controls as
NOT RUN, `vip trace` warns on stderr, and the JSON summary counts them under
`covered_not_executed`. Read `gaps: 0` together with that number.

Coverage is not completeness. The matrix reports on the controls in your
control list. A control you never wrote down cannot appear as a gap.

A green report is not an attestation of compliance. It is one input to a
validation exercise that you own.

## See also

- `README.md`, next to this file, for the worked control list and tagged
  scenarios, including the scope limits specific to 21 CFR Part 11
- [the reporting guide](https://github.com/posit-dev/vip/blob/main/docs/reporting.md)
  for the machine-readable outputs, the `vip trace` export, and the checksum
  sidecar
- [the test architecture guide](https://github.com/posit-dev/vip/blob/main/docs/test-architecture.md)
  for control tagging and the four-layer test architecture
