"""Format-neutral content model for the VIP report.

``vip.reporting`` is the pure data layer (``TestResult``/``ReportData``, plus
JSON/JUnit/SARIF I/O). This module sits between that layer and the two
rendering backends:

* ``vip.report_html`` — HTML fragments for ``report/index.qmd`` and
  ``report/details.qmd`` (the browsable report).
* ``vip.report_typst`` — Typst markup for ``report/vip-report.qmd`` (the
  archivable PDF).

Everything here answers "what does the reader see", never "what markup says
it". Placeholder substitution, card titles, outcome and marker styling,
grouping, Gherkin step lookup, skip wording, and provenance rows are all
identical in both outputs, so they live here once. A backend adds only the
markup.

Colors are part of this model rather than of one backend's stylesheet. The
HTML report reads them from ``report/styles.css`` and the PDF cannot, so the
value has to exist in Python for Typst to use it.
``selftests/test_report_content.py`` parses ``styles.css`` and fails if the
two ever disagree.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from vip.gherkin import parse_feature_file
from vip.reporting import ReportData, TestResult, feature_file_for_nodeid

# ---------------------------------------------------------------------------
# <param> placeholder substitution
# ---------------------------------------------------------------------------

# A pytest-parametrize suffix on a nodeid, e.g. "...::test_x[cran]" -> "cran".
_PARAM_SUFFIX_RE = re.compile(r"\[(.+)\]$")
# A Gherkin Scenario Outline placeholder left in scenario_title, e.g. "<repo>".
_PLACEHOLDER_RE = re.compile(r"<[^>]+>")


def substitute_param_placeholders(nodeid: str, title: str) -> str:
    """Replace Scenario Outline ``<placeholder>`` tokens with their pytest value.

    pytest-bdd's Scenario Outline expansion leaves the Gherkin placeholder
    syntax (e.g. "Install <package> from CRAN") in ``scenario_title`` and puts
    the actual parametrize value in the nodeid's trailing ``[...]`` instead.
    Hoisted out of the per-card loop both templates used to have — each did
    ``import re as _re`` inside the loop (F13) — and shared, since both pages
    need the identical substitution.
    """
    if "<" not in title:
        return title
    match = _PARAM_SUFFIX_RE.search(nodeid)
    if not match:
        return title
    return _PLACEHOLDER_RE.sub(match.group(1), title)


def display_title(item: TestResult) -> str:
    """The card's title: the scenario title (or bare test name), placeholders resolved."""
    raw = item.scenario_title or (
        item.nodeid.split("::")[-1] if "::" in item.nodeid else item.nodeid
    )
    return substitute_param_placeholders(item.nodeid, raw)


def pluralize(count: int, noun: str = "test") -> str:
    """'1 test' vs '2 tests' (F13 — the live report showed '1 tests')."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


# ---------------------------------------------------------------------------
# Outcome styling (PASS/FAIL/SKIP/N-A badges, section colors)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutcomeStyle:
    label: str
    color: str
    background: str


_OUTCOME_STYLES: dict[str, OutcomeStyle] = {
    "passed": OutcomeStyle("PASS", "#16a34a", "#dcfce7"),
    "failed": OutcomeStyle("FAIL", "#dc2626", "#fecaca"),
    "skipped": OutcomeStyle("SKIP", "#6b7280", "#e5e7eb"),
    "na_version": OutcomeStyle("N/A", "#d97706", "#fde68a"),
}
_DEFAULT_OUTCOME_STYLE = OutcomeStyle("?", "#6b7280", "#e5e7eb")

# Order and label for the outcome-grouped sections on index.qmd (failures are
# the actionable ones, so they lead).
OUTCOME_ORDER = ("failed", "skipped", "na_version")
OUTCOME_LABELS = {
    "failed": "Failed",
    "passed": "Passed",
    "skipped": "Skipped",
    "na_version": "N/A (version)",
}


def outcome_style(status: str) -> OutcomeStyle:
    """Styling for a ``TestResult.status`` value; an unrecognized one degrades to grey."""
    return _OUTCOME_STYLES.get(status, _DEFAULT_OUTCOME_STYLE)


# ---------------------------------------------------------------------------
# Marker badges (F8)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Badge:
    css_class: str
    label: str
    color: str
    """Fill for a primary pill, text color for a secondary one.

    Duplicated from ``report/styles.css`` on purpose: the PDF backend has no
    stylesheet to read. ``TestBadgeColors`` in
    ``selftests/test_report_content.py`` fails if the two copies drift.
    """


# Primary badges: one loud, colored pill per matching marker on a card.
# Every top-level test category (see AGENTS.md's four-layer architecture doc
# / src/vip_tests/*) is covered, so a scenario carrying no *product* marker
# at all — e.g. a performance/cross_product/config_hygiene scenario, none of
# which are `@connect`/`@workbench`/`@package_manager` — still gets one
# informative pill instead of no badge at all (F8: previously only 5 of
# these were known, and cross_product/config_hygiene/performance cards were
# indistinguishable from any other card in the same category section).
PRIMARY_BADGES: dict[str, Badge] = {
    "connect": Badge("badge-connect", "Connect", "#447099"),
    "workbench": Badge("badge-workbench", "Workbench", "#72994e"),
    "package_manager": Badge("badge-package-manager", "Package Manager", "#9a4665"),
    "security": Badge("badge-security", "Security", "#d4526e"),
    "prerequisites": Badge("badge-prerequisites", "Prerequisites", "#6c757d"),
    "cross_product": Badge("badge-cross-product", "Cross-Product", "#7c5cbf"),
    "config_hygiene": Badge("badge-config-hygiene", "Config Hygiene", "#b45309"),
    "performance": Badge("badge-performance", "Performance", "#0891b2"),
}

# Secondary badges: quiet, informational only, never drive grouping. Chosen
# judiciously (F8) — not every one of pyproject.toml's 16 registered markers
# earns a badge. The IDE markers tell a reader which IDE a Workbench card
# exercised (previously invisible anywhere in the report). `slow` flags a
# scenario that `vip verify --basic` skips, worth one small tag rather than
# a second loud pill duplicating the card's product badge. Structural
# markers (`min_version`, `if_applicable`, `api_auth`) describe *how* VIP
# decided to run the test, not something a reader validating a deployment
# needs to see, so they render nothing.
SECONDARY_BADGES: dict[str, Badge] = {
    "rstudio": Badge("badge-ide", "RStudio", "#4b5563"),
    "vscode": Badge("badge-ide", "VS Code", "#4b5563"),
    "jupyter": Badge("badge-ide", "JupyterLab", "#4b5563"),
    "positron": Badge("badge-ide", "Positron", "#4b5563"),
    "slow": Badge("badge-slow", "Slow", "#4b5563"),
}

# Border and fill for a secondary badge. Shared by both backends for the same
# reason the per-badge color is: styles.css is unavailable to Typst.
SECONDARY_BADGE_BACKGROUND = "#f3f4f6"
SECONDARY_BADGE_BORDER = "#d1d5db"


def primary_badges_for(item: TestResult) -> list[Badge]:
    """Every primary badge present in ``item.markers`` (may be more than one)."""
    return [PRIMARY_BADGES[m] for m in item.markers if m in PRIMARY_BADGES]


def secondary_badges_for(markers: list[str]) -> list[Badge]:
    """The quiet IDE/slow badges for a card, in ``SECONDARY_BADGES`` order."""
    return [badge for marker, badge in SECONDARY_BADGES.items() if marker in markers]


def category_for(item: TestResult) -> str:
    """The top-level test category used to group cards (F6) and roll up
    per-product counts (F7).

    Prefers the scenario's own marker (its ``@connect``/``@workbench``/...
    tag) over the directory it happens to live in, because the marker is what
    the scenario asserts about rather than an artefact of file layout: a
    cross-product scenario filed under one product's directory still belongs
    with the product it is tagged for. Falls back to ``TestResult.category``,
    which derives the category from the nodeid path.
    """
    for marker in item.markers:
        if marker in PRIMARY_BADGES:
            return marker
    return item.category


def results_for_product(results: list[TestResult], product: str) -> list[TestResult]:
    """Every result that counts toward *product*'s row in the rollup (F7).

    A result counts when it is tagged for the product *or* lives in the
    product's directory. Deliberately broader than ``category_for``, which
    assigns each result to exactly one bucket: a scenario tagged for two
    products genuinely exercised both, so a single-bucket rule would silently
    under-count one of them. The consequence is that the product rows do not
    sum to the run total, which was already true (``prerequisites`` and
    ``security`` results belong to no product row at all) and is why the
    Summary table carries the authoritative totals.
    """
    return [r for r in results if product in r.markers or r.category == product]


def group_by_category(results: list[TestResult]) -> dict[str, list[TestResult]]:
    """Group results by ``category_for`` (see its docstring for why not
    ``ReportData.by_category``), preserving each category's first-seen order."""
    groups: dict[str, list[TestResult]] = {}
    for item in results:
        groups.setdefault(category_for(item), []).append(item)
    return groups


def category_label(category: str) -> str:
    """ "package_manager" -> "Package Manager" for a section heading."""
    return category.replace("_", " ").title()


def outcome_counts_summary(items: list[TestResult]) -> str:
    """ "6 passed, 1 failed, 2 skipped" — used in category/group sub-headers."""
    counts = Counter(i.status for i in items)
    order = [
        ("passed", "passed"),
        ("failed", "failed"),
        ("skipped", "skipped"),
        ("na_version", "N/A (version)"),
    ]
    parts = [f"{counts[key]} {label}" for key, label in order if counts.get(key)]
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Feature-file step lookup (cached per page render)
# ---------------------------------------------------------------------------


class FeatureStepIndex:
    """Caches parsed ``.feature`` files across one page render.

    Both templates look up the Gherkin steps for potentially dozens of cards
    backed by a handful of ``.feature`` files. Each Quarto page is a fresh
    Python kernel, so an instance only needs to live as long as one page —
    construct one per page-level render call.
    """

    def __init__(self) -> None:
        self._cache: dict[str, dict] = {}

    def _feature(self, nodeid: str) -> dict | None:
        feature_file = feature_file_for_nodeid(nodeid)
        key = str(feature_file) if feature_file else nodeid
        if key not in self._cache:
            self._cache[key] = parse_feature_file(feature_file) if feature_file else {}
        return self._cache[key] or None

    def steps_for(self, item: TestResult) -> list[str]:
        feature = self._feature(item.nodeid)
        if not feature or not feature.get("scenarios") or not item.scenario_title:
            return []
        for scenario in feature["scenarios"]:
            if scenario["title"] == item.scenario_title and scenario.get("steps"):
                return scenario["steps"]
        return []


# ---------------------------------------------------------------------------
# Feature description (F4)
# ---------------------------------------------------------------------------


def dominant_feature_description(results: list[TestResult]) -> str | None:
    """The most common non-empty feature-description first line across a run.

    Almost every VIP feature file opens with the same Gherkin user-story line
    ("As a Posit Team administrator..."), so showing it on every card is pure
    repetition (F4) — but a handful of files genuinely differ ("As a VIP
    user...", "...running Workbench on Kubernetes"), and that difference is
    worth surfacing. Rather than drop the field outright, compute the
    majority value for the whole run and only render a card's description
    when it differs from that majority — see ``description_line``.
    """
    first_lines = [
        line
        for r in results
        if r.feature_description and (line := r.feature_description.split("\n")[0].strip())
    ]
    if not first_lines:
        return None
    return Counter(first_lines).most_common(1)[0][0]


def description_line(item: TestResult, dominant: str | None) -> str:
    """The card's description line, or "" when it repeats the run's dominant one."""
    if not item.feature_description:
        return ""
    first_line = item.feature_description.split("\n")[0].strip()
    if not first_line or first_line == dominant:
        return ""
    return first_line


# ---------------------------------------------------------------------------
# Skip reason (F3)
# ---------------------------------------------------------------------------

NA_VERSION_EXPLANATION = (
    "Skipped because the product's version could not be determined, so VIP "
    "could not tell whether this check applies."
)


def skip_reason_parts(item: TestResult) -> tuple[str, str]:
    """The wording for a skip card (F3), as ``(explanation, detail)``.

    Returns ``("", "")`` for a card that is not skipped. ``detail`` is "" when
    there is nothing to add beyond the explanation, and both backends render
    it more quietly than the explanation it follows.

    ``na_version`` reads distinctly from an ordinary skip (see
    ``TestResult.status``): it leads with plain-English wording, because the
    raw reason is phrased for whoever is debugging VIP rather than for whoever
    is reading the report. It does *not* stop there. ``_skip_version_unknown``
    records which product and which ``min_version`` expression it could not
    evaluate, and that detail is the only actionable part of the card, so it
    comes back as ``detail`` instead of replacing the explanation.

    An ordinary skip shows its ``skip_reason`` when the plugin recorded one,
    and a neutral placeholder rather than silence when it did not (a
    ``results.json`` written before the field existed, say).
    """
    if item.outcome != "skipped":
        return "", ""
    if item.status == "na_version":
        return NA_VERSION_EXPLANATION, (item.skip_reason or "").strip()
    # ``.strip()`` guards a results.json written before the plugin started
    # normalising this: a whitespace-only reason is truthy and would render as
    # a blank line instead of the fallback wording.
    return (item.skip_reason or "").strip() or "No reason recorded.", ""


# ---------------------------------------------------------------------------
# Provenance (F9)
# ---------------------------------------------------------------------------

# pytest's documented exit codes (https://docs.pytest.org/en/stable/reference/exit-codes.html).
EXIT_STATUS_LABELS = {
    0: "OK — no failures",
    1: "tests were collected and run, but some failed",
    2: "run was interrupted by the user",
    3: "an internal error occurred",
    4: "pytest command line usage error",
    5: "no tests were collected",
}

# Rendered in place of a provenance field that the run never recorded.
NOT_RECORDED = "not recorded"


def _execution_rows(execution: dict | None) -> list[tuple[str, str | None]]:
    """Who ran this, on which host, from which commit, under which CI job.

    ``results.json`` has recorded this block since attribution landed, but
    until now only ``vip trace --format json`` rendered it. The report is the
    artifact a customer archives and hands to an auditor, so a result that is
    attributable in the machine-readable output and anonymous in the PDF is
    attributable in the wrong place.

    The whole block is omitted rather than shown as five ``NOT_RECORDED`` rows
    when ``execution`` is absent: that is what ``--vip-no-attribution`` asked
    for, and repeating "not recorded" five times reads as a broken run rather
    than a deliberate one. Within a present block, an individual missing field
    still follows the ``None`` contract above.
    """
    if not execution:
        return []
    git = execution.get("git") or {}
    ci = execution.get("ci") or {}
    performer = execution.get("performed_by") or {}

    commit = git.get("commit")
    if commit and git.get("dirty"):
        # An uncommitted tree means the evidence cannot be reproduced from the
        # commit alone. That belongs next to the commit, not in a footnote.
        commit = f"{commit} (uncommitted changes present)"

    identity = performer.get("identity")
    if identity and performer.get("source") == "login":
        # A local login is who was at the keyboard, which is weaker than a
        # named operator or a CI actor. Say which one the reader is looking at.
        identity = f"{identity} (local login)"

    return [
        ("Performed by", identity),
        ("Run host", execution.get("hostname")),
        ("Commit", commit),
        ("Branch", git.get("branch")),
        ("CI run", ci.get("run_url") or ci.get("run_id")),
    ]


def provenance_rows(data: ReportData) -> list[tuple[str, str | None]]:
    """VIP version, run duration, interpreter/platform, mode, exit status (F9),
    then the execution attribution block when the run recorded one.

    A ``None`` value means the field is absent from this ``results.json`` and
    the backend must render ``NOT_RECORDED`` rather than a fabricated value.
    Every field but ``exit_status`` is ``None`` on a ``results.json`` written
    before Phase 1 added them — see ``ReportData``'s own docstring for why
    that matters for an artifact a customer archives as evidence.
    """
    duration = (
        f"{data.run_duration_seconds:.1f}s" if data.run_duration_seconds is not None else None
    )
    mode = None if data.basic_mode is None else ("basic" if data.basic_mode else "full")
    exit_label = EXIT_STATUS_LABELS.get(data.exit_status, "unrecognized exit code")
    return [
        ("VIP version", data.vip_version),
        ("Run duration", duration),
        ("Python", data.python_version),
        ("Platform", data.platform),
        ("Mode", mode),
        ("Exit status", f"{data.exit_status} ({exit_label})"),
        *_execution_rows(data.execution),
    ]


def summary_status(data: ReportData) -> str:
    """The run's overall verdict: "FAIL" when anything failed, else "PASS"."""
    return "FAIL" if data.failed else "PASS"


# ---------------------------------------------------------------------------
# Compliance traceability section
# ---------------------------------------------------------------------------

# Coverage values reuse the outcome palette rather than introducing new colors,
# so `selftests/test_report_content.py`'s drift guard against styles.css keeps
# working unchanged. The mapping is the honest one: a gap reads like a failure,
# an executed covered control like a pass, a control with no automated test to
# point at like a skip, and a covered control whose scenarios never ran like
# na_version -- amber, because it is the state most likely to be misread as
# evidence. A covered control whose scenarios ran without passing uses the red
# of a gap, because both mean the control is not evidenced.
COVERAGE_STYLE_KEY = {
    "covered": "passed",
    "covered_not_executed": "na_version",
    "covered_failed": "failed",
    "gap": "failed",
    "not_automatable": "skipped",
}

COVERAGE_LABELS = {
    "covered": "COVERED",
    "covered_not_executed": "NOT RUN",
    "covered_failed": "FAILED",
    "gap": "GAP",
    "not_automatable": "N/A (manual)",
}


@dataclass(frozen=True)
class ControlRow:
    """One control's line in the rendered traceability section."""

    control_id: str
    description: str
    reference: str
    risk: str
    """The customer's own risk rating, carried through uninterpreted.

    Rendered because FDA's Computer Software Assurance guidance asks the
    record to carry the result of the risk-based analysis, and because a
    reviewer triaging a matrix reads the high-risk gaps first. VIP does not
    rank or validate the value -- ``risk = "banana"`` renders as "banana".
    """
    coverage: str
    """"covered" | "covered_not_executed" | "covered_failed" | "gap" |
    "not_automatable".

    Distinct from ``ControlEntry.coverage``, which has no
    ``covered_not_executed`` or ``covered_failed`` value: the matrix keeps
    coverage, execution and outcome as separate facts, and this flattens them
    for display because a reader scanning one column must not read an
    all-skipped or all-failing control as evidenced.
    """
    scenarios: list[tuple[str, str, str]]
    """``(scenario title, status, when it ran)`` for each matched scenario."""


def display_coverage(entry) -> str:  # noqa: ANN001 - vip.traceability.ControlEntry
    """Flatten coverage, execution and outcome into the one value the report shows."""
    if entry.coverage == "covered" and entry.failing:
        return "covered_failed"
    if entry.coverage == "covered" and not entry.executed:
        return "covered_not_executed"
    return entry.coverage


def control_rows(matrix) -> list[ControlRow]:  # noqa: ANN001 - TraceabilityMatrix
    """Every control in the matrix, ready for a backend to render as a table."""
    rows = []
    for entry in matrix.entries:
        scenarios = [
            (
                m.scenario_title or m.nodeid,
                m.status,
                (m.started_at or "").replace("T", " ")[:19] or NOT_RECORDED,
            )
            for m in entry.matches
        ]
        rows.append(
            ControlRow(
                control_id=entry.control.control_id,
                description=entry.control.description,
                reference=entry.control.reference or "",
                risk=entry.control.risk or "",
                coverage=display_coverage(entry),
                scenarios=scenarios,
            )
        )
    return rows


def traceability_summary_rows(matrix) -> list[tuple[str, str]]:  # noqa: ANN001
    """Label/value counts for the section's summary table."""
    rows = control_rows(matrix)
    counts = Counter(r.coverage for r in rows)
    return [
        ("Controls", str(len(rows))),
        ("Covered, executed and passing", str(counts.get("covered", 0))),
        ("Covered, not executed", str(counts.get("covered_not_executed", 0))),
        ("Covered, failing", str(counts.get("covered_failed", 0))),
        ("Gaps", str(counts.get("gap", 0))),
        ("Not automatable", str(counts.get("not_automatable", 0))),
    ]


# Shown under the section heading in both backends. The report is the artifact
# a customer archives, so the limits of the claim travel with it rather than
# living only in the docs they may never read.
TRACEABILITY_CAVEAT = (
    "Coverage records that a scenario is tagged for a control, not that the "
    "scenario passed or even ran. A control shown as NOT RUN has a tagged "
    "scenario that ran and skipped itself, because this deployment does not "
    "expose what it probes or a version gate excluded it. A control shown as "
    "a GAP may instead belong to a product this run did not test, since those "
    "scenarios are excluded from the run and reach no result at all. "
    "A control shown as FAILED has a tagged scenario that ran and did not pass, "
    "so the control is not evidenced by this run. This "
    "section evidences the controls chosen for automation. It is not an "
    "attestation of regulatory compliance."
)

# Both editions render this identically when the section cannot be built. A
# compliance report that drops the section without saying so is the one
# outcome a regulated reader cannot detect.
TRACEABILITY_RENDER_FAILURE = "Could not render the traceability section: {error}"


def traceability_warnings(matrix) -> list[str]:  # noqa: ANN001
    """Lines naming controls that look covered but are not evidence.

    Two independent conditions, so two lines rather than one combined
    sentence: a control can be counted as covered because nothing ran, or
    because what ran did not pass, and a reader needs to know which.
    """
    lines = []
    failing = matrix.covered_with_failure
    if failing:
        lines.append(
            f"{pluralize(len(failing), 'control')} counted as covered but had a "
            f"scenario that did not pass: {', '.join(failing)}."
        )
    unexecuted = matrix.covered_without_execution
    if unexecuted:
        lines.append(
            f"{pluralize(len(unexecuted), 'control')} counted as covered but had no "
            f"scenario that ran: {', '.join(unexecuted)}."
        )
    return lines
