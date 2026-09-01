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

Execution provenance. Each results file records who ran the tests, which host
they ran on, which git commit and branch they came from, whether that tree was
dirty, and which CI job produced them. The HTML report and the PDF render the
attribution as well, so the archived artifact carries it rather than only the
machine-readable output. This is what makes a result attributable to a named
operator and a pipeline execution rather than to an anonymous green tick.

Set `VIP_PERFORMED_BY` to record the person accountable for the run. Without
it, VIP falls back to the CI system's actor, then to the local login, and the
report qualifies the name with where it came from -- `octocat (GitHub actor)`
rather than a bare `octocat`. An explicitly named operator is the only one
that renders unqualified, because it is the only one a human chose. A CI actor
is frequently a service account, and on a scheduled run it is whoever last
edited the workflow. `--vip-no-attribution` omits the whole block for anyone
who does not want an operator identity written into an archived file.

Tamper-evidence. A `results.json.sha256` sidecar detects corruption in transit,
a truncated upload, or a file edited after the fact and not re-checksummed.

Read that last one precisely. It is tamper-evidence within a trusted pipeline,
not tamper-proofing and not an immutable audit trail. Anyone who can edit the
results file can regenerate the sidecar to match. It catches accidents, which
is the failure that actually happens to archived CI artifacts. It does not
resist a motivated forger, and it must never be presented as though it does.

## Where this sits in FDA's current thinking

FDA finalised [Computer Software Assurance for Production and Quality
Management System
Software](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/computer-software-assurance-production-and-quality-management-system-software)
in September 2025 and updated it in February 2026. Two passages in section
V.A.6, "Establishing the Appropriate Record", matter for anyone deciding what
VIP is worth.

The first describes what VIP produces almost by name. Advances in digital
technology, the guidance says, "may allow for manufacturers to leverage
digital retention of results, automated traceability, automated testing, and
electronic capture of work performed as objective evidence, reducing the need
for manual or paper-based documentation." It then recommends, as the
least-burdensome approach, "incorporating the use of digital records, such as
system logs, audit trails, and other data generated and maintained by the
software, as opposed to paper documentation, screenshots, or duplicating
results already digitally retained by the software when establishing the
record associated with the assurance activities." A machine-generated results
file with per-scenario timestamps and execution provenance is the artifact
those sentences describe. Screenshots pasted into a Word protocol are what
they discourage.

The second is the list of what the record should include. VIP covers, in whole
or in part:

- the intended use of the feature or function, insofar as your control
  descriptions state it
- the result of your risk-based analysis, carried through from `controls.toml`
  and rendered in the matrix
- a description of the testing conducted, as the tagged scenario and its steps
- issues found during testing, as failed and skipped scenarios
- who performed the testing and the date it was performed

Two items are yours. VIP writes no conclusion statement declaring
acceptability, and it carries no resolution against the issues it records:
both are judgements, not test results. Neither is there any review and
approval signature, which the guidance asks for "when appropriate" and which
belongs in your quality system.

None of this makes a VIP run a computer software assurance activity on its
own. The approach is risk-based, and the risk analysis that decides how much
assurance a function needs is yours.

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

If you need results to resist a motivated forger rather than only to detect
corruption, sign them in your pipeline rather than waiting for VIP to grow its
own crypto. On GitHub Actions, `actions/attest-build-provenance` produces a
Sigstore-backed attestation over `results.json` that is recorded in a public
transparency log, and `gh attestation verify` checks it later. That gives you
what the sha256 sidecar deliberately does not claim: a signature the producer
cannot quietly regenerate.

## Reading a green report

A fully green matrix evidences the controls you chose to automate, on the
deployment you pointed it at, at the time it ran. That is all it claims.

Five specific ways it can mislead if read carelessly:

Coverage is not execution. A control counts as covered when a scenario is
tagged for it, whether or not that scenario reached an assertion. A scenario
that ran and skipped itself still covers its control: the endpoint it probes is
absent from this deployment, there was no data to inspect, or a version gate
excluded it. The report shows those controls as NOT RUN, `vip trace` warns on
stderr, and the JSON summary counts them under `covered_not_executed`. Read
`gaps: 0` together with that number.

Execution is not verification either. A scenario can run, find that it cannot
check what it was asked to check, and record that as unproven rather than as a
pass. Such a control shows as UNPROVEN, warns on stderr, and is counted under
`covered_unproven`. This is the one case the two numbers above miss entirely:
a control with one passing scenario beside one unproven scenario is both
executed and not failing, so it reads as fully evidenced from those two alone
while part of the control went unchecked.

A gap can be an artifact of the run rather than of your suite. Scenarios
belonging to a product you did not configure are deselected, not skipped, so
they never appear in the results file at all, and a control tagged only by them
reports as a gap. This errs toward understating your coverage, which is the
safer direction, but the reading is still wrong: the suite has the check, the
run did not exercise it. Check the products the report says were under test
before you conclude a control has no automated evidence. The worked example
next to this file maps controls across Connect, Workbench and Package Manager,
so a run covering one product shows gaps for the other two.

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
