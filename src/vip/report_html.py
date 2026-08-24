"""HTML rendering for the VIP Quarto report.

``vip.reporting`` is the pure data layer (``TestResult``/``ReportData``, plus
JSON/JUnit/SARIF I/O). This module is its rendering sibling: it turns that
data into the HTML fragments ``report/index.qmd`` and ``report/details.qmd``
hand to ``IPython.display.HTML()``. It exists so the rendering logic — card
markup, badges, the ``<param>`` substitution, the copy-to-clipboard script —
is plain, testable Python instead of duplicated inline in two Quarto chunks,
where nothing can reach it with a test.

Escaping is a security property here, not a style choice: the report is
published publicly (https://posit-dev.github.io/vip/example-report/) and
embeds test titles, error messages, and troubleshooting hints taken straight
from test output and Gherkin source. Every value interpolated into the HTML
this module returns goes through ``html.escape`` — do not add an
interpolation that skips it.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from html import escape as _esc

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


def _pluralize(count: int, noun: str = "test") -> str:
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


def outcome_badge_html(status: str) -> str:
    style = outcome_style(status)
    return (
        f'<span class="vip-badge" style="color:{style.color};background:{style.background}">'
        f"{_esc(style.label)}</span>"
    )


# ---------------------------------------------------------------------------
# Marker badges (F8)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Badge:
    css_class: str
    label: str


# Primary badges: one loud, colored pill per matching marker on a card.
# Every top-level test category (see AGENTS.md's four-layer architecture doc
# / src/vip_tests/*) is covered, so a scenario carrying no *product* marker
# at all — e.g. a performance/cross_product/config_hygiene scenario, none of
# which are `@connect`/`@workbench`/`@package_manager` — still gets one
# informative pill instead of no badge at all (F8: previously only 5 of
# these were known, and cross_product/config_hygiene/performance cards were
# indistinguishable from any other card in the same category section).
_PRIMARY_BADGES: dict[str, Badge] = {
    "connect": Badge("badge-connect", "Connect"),
    "workbench": Badge("badge-workbench", "Workbench"),
    "package_manager": Badge("badge-package-manager", "Package Manager"),
    "security": Badge("badge-security", "Security"),
    "prerequisites": Badge("badge-prerequisites", "Prerequisites"),
    "cross_product": Badge("badge-cross-product", "Cross-Product"),
    "config_hygiene": Badge("badge-config-hygiene", "Config Hygiene"),
    "performance": Badge("badge-performance", "Performance"),
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
_SECONDARY_BADGES: dict[str, Badge] = {
    "rstudio": Badge("badge-ide", "RStudio"),
    "vscode": Badge("badge-ide", "VS Code"),
    "jupyter": Badge("badge-ide", "JupyterLab"),
    "positron": Badge("badge-ide", "Positron"),
    "slow": Badge("badge-slow", "Slow"),
}


def _badge_html(badge: Badge) -> str:
    return f'<span class="{badge.css_class}">{_esc(badge.label)}</span>'


def secondary_badges_html(markers: list[str]) -> str:
    return "".join(
        _badge_html(badge) for marker, badge in _SECONDARY_BADGES.items() if marker in markers
    )


def product_badges_html(item: TestResult) -> str:
    """Every primary badge present in ``item.markers`` (may be more than one),
    followed by any secondary (IDE/slow) badges."""
    primary = "".join(_badge_html(_PRIMARY_BADGES[m]) for m in item.markers if m in _PRIMARY_BADGES)
    return primary + secondary_badges_html(item.markers)


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
        if marker in _PRIMARY_BADGES:
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


# ---------------------------------------------------------------------------
# Feature-file step lookup (cached per page render)
# ---------------------------------------------------------------------------


class FeatureStepIndex:
    """Caches parsed ``.feature`` files across one page render.

    Both templates look up the Gherkin steps for potentially dozens of cards
    backed by a handful of ``.feature`` files. Each Quarto page is a fresh
    Python kernel, so an instance only needs to live as long as one page —
    construct one per ``render_details_page``/``render_actionable_cards`` call.
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


def steps_html(steps: list[str]) -> str:
    if not steps:
        return ""
    items = "".join(f"<li>{_esc(s)}</li>" for s in steps)
    return (
        f'<details class="vip-test-steps"><summary>Test procedure</summary>'
        f'<ul class="vip-step-list">{items}</ul></details>'
    )


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
    when it differs from that majority — see ``description_html``.
    """
    first_lines = [
        line
        for r in results
        if r.feature_description and (line := r.feature_description.split("\n")[0].strip())
    ]
    if not first_lines:
        return None
    return Counter(first_lines).most_common(1)[0][0]


def description_html(item: TestResult, dominant: str | None) -> str:
    if not item.feature_description:
        return ""
    first_line = item.feature_description.split("\n")[0].strip()
    if not first_line or first_line == dominant:
        return ""
    return f'<div class="vip-test-description">{_esc(first_line)}</div>'


# ---------------------------------------------------------------------------
# Skip reason (F3)
# ---------------------------------------------------------------------------

_NA_VERSION_EXPLANATION = (
    "Skipped because the product's version could not be determined, so VIP "
    "could not tell whether this check applies."
)


def skip_reason_html(item: TestResult) -> str:
    """An explanation for a skip card (F3).

    ``na_version`` reads distinctly from an ordinary skip (see
    ``TestResult.status``): it leads with plain-English wording, because the
    raw reason is phrased for whoever is debugging VIP rather than for whoever
    is reading the report. It does *not* stop there. ``_skip_version_unknown``
    records which product and which ``min_version`` expression it could not
    evaluate, and that detail is the only actionable part of the card, so it
    follows the explanation instead of being replaced by it.

    An ordinary skip shows its ``skip_reason`` when the plugin recorded one,
    and a neutral placeholder rather than silence when it did not (a
    ``results.json`` written before the field existed, say).
    """
    if item.outcome != "skipped":
        return ""
    if item.status == "na_version":
        parts = [_esc(_NA_VERSION_EXPLANATION)]
        if item.skip_reason and item.skip_reason.strip():
            detail = _esc(item.skip_reason.strip())
            parts.append(f'<span class="vip-skip-detail">{detail}</span>')
        return f'<div class="vip-skip-reason">{"".join(parts)}</div>'
    # ``.strip()`` guards a results.json written before the plugin started
    # normalising this: a whitespace-only reason is truthy and would render as
    # a blank line instead of the fallback wording.
    reason = (item.skip_reason or "").strip() or "No reason recorded."
    return f'<div class="vip-skip-reason">{_esc(reason)}</div>'


# ---------------------------------------------------------------------------
# Error + troubleshooting hints (F2 — one shared behaviour for both pages)
# ---------------------------------------------------------------------------


def error_html(item: TestResult, error_id: str) -> str:
    """Concise error message, with the full traceback behind a collapsed ``<details>``.

    F2: this used to differ between pages — ``details.qmd`` showed the
    concise message up front with the traceback collapsed; ``index.qmd``
    showed only the raw ``longrepr``, with no concise line at all, so the
    public summary's only visible explanation for a FAIL was pytest's own
    traceback text. This is the one shared behaviour now: the concise
    message (already cleaned up by the plugin) is always visible; the full
    traceback — which can include internal fixture frames and absolute
    filesystem paths — stays behind a click on both pages.
    """
    if item.outcome != "failed":
        return ""
    parts = []
    if item.concise_error:
        parts.append(f'<div class="vip-fail-concise">{_esc(item.concise_error)}</div>')
    if item.longrepr:
        parts.append(
            f'<details class="vip-fail-details">'
            f"<summary>Full error traceback</summary>"
            f'<div class="vip-fail-error-wrap">'
            f'<button class="vip-copy-btn" data-target="{error_id}" title="Copy to clipboard">'
            f"Copy</button>"
            f'<pre id="{error_id}" class="vip-fail-error">{_esc(item.longrepr)}</pre>'
            f"</div></details>"
        )
    return "".join(parts)


def hints_html(item: TestResult, hints: dict[str, dict]) -> str:
    """Troubleshooting hints for a failed card, keyed by ``scenario_title``."""
    if item.outcome != "failed" or not item.scenario_title:
        return ""
    hint = hints.get(item.scenario_title) or {}
    if not hint:
        return ""
    parts: list[str] = []
    if hint.get("likely_causes"):
        parts.append("<strong>Likely causes:</strong><ul>")
        parts.extend(f"<li>{_esc(cause)}</li>" for cause in hint["likely_causes"])
        parts.append("</ul>")
    if hint.get("suggested_steps"):
        parts.append("<strong>Suggested next steps:</strong><ol>")
        parts.extend(f"<li>{_esc(step)}</li>" for step in hint["suggested_steps"])
        parts.append("</ol>")
    if hint.get("docs_url"):
        url = _esc(hint["docs_url"])
        parts.append(
            f"<p><strong>Documentation:</strong> "
            f'<a href="{url}" target="_blank" rel="noopener">{url}</a></p>'
        )
    if not parts:
        return ""
    return f'<div class="vip-fail-hints">{"".join(parts)}</div>'


# ---------------------------------------------------------------------------
# Card rendering
# ---------------------------------------------------------------------------


def render_card(
    item: TestResult,
    *,
    index: int,
    feature_index: FeatureStepIndex,
    hints: dict[str, dict],
    dominant_description: str | None,
) -> str:
    """Render one test result as a self-contained card.

    ``index`` seeds the copy-button element id (``vip-error-{index}``) and
    must be unique across the whole page — callers enumerate every card they
    render on a page with one running counter, not one per section, so two
    sections on the same page never collide.
    """
    style = outcome_style(item.status)
    title = _esc(display_title(item))
    nodeid = _esc(item.nodeid)
    duration = f"{item.duration:.2f}s"
    badge = outcome_badge_html(item.status)
    badges = product_badges_html(item)
    description = description_html(item, dominant_description)
    skip_reason = skip_reason_html(item)
    steps = steps_html(feature_index.steps_for(item))
    error = error_html(item, f"vip-error-{index}")
    hint = hints_html(item, hints)
    return (
        f'<div class="vip-test-card" style="border-left-color:{style.color}">'
        f'<div class="vip-test-header">{badge}'
        f'<span class="vip-test-scenario">{title}</span>{badges}</div>'
        f"{description}{skip_reason}"
        f'<div class="vip-test-meta">{nodeid}'
        f'<span class="vip-test-duration">{_esc(duration)}</span></div>'
        f"{steps}{error}{hint}"
        f"</div>"
    )


def _outcome_counts_summary(items: list[TestResult]) -> str:
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


# Copy-to-clipboard behaviour for every "Copy" button on a page. Static and
# shared by both templates; appended once per page after all cards.
CLIPBOARD_SCRIPT = """
<script>
document.querySelectorAll('.vip-copy-btn').forEach(function(btn) {
  btn.addEventListener('click', function() {
    var target = document.getElementById(btn.getAttribute('data-target'));
    if (!target) return;
    navigator.clipboard.writeText(target.textContent).then(function() {
      btn.textContent = 'Copied!';
      setTimeout(function() { btn.textContent = 'Copy'; }, 2000);
    });
  });
});
</script>
"""


# Expand every collapsed section for the duration of a print, then restore it.
# The print stylesheet handles engines that support ::details-content, but not
# every browser a customer prints from does, and a report that silently omits
# its tracebacks on paper is worse than one that omits them on screen. Safari
# has historically not fired onbeforeprint, so the matchMedia listener covers
# it. Restoring on the way out keeps the on-screen state the reader chose.
PRINT_EXPAND_SCRIPT = """
<script>
(function() {
  // null means "not currently expanded for print". Both handlers below fire on
  // a real print in Chromium, so expand() runs twice; without this guard the
  // second call finds nothing closed, resets the record to empty, and restore()
  // then re-collapses nothing, leaving the reader's report permanently expanded
  // after they print it. Redundant paths have to be idempotent.
  var expanded = null;
  function expand() {
    if (expanded) return;
    expanded = [];
    document.querySelectorAll('details:not([open])').forEach(function(d) {
      expanded.push(d);
      d.open = true;
    });
  }
  function restore() {
    if (!expanded) return;
    expanded.forEach(function(d) { d.open = false; });
    expanded = null;
  }
  window.addEventListener('beforeprint', expand);
  window.addEventListener('afterprint', restore);
  if (window.matchMedia) {
    var mq = window.matchMedia('print');
    var onChange = function(e) { (e.matches ? expand : restore)(); };
    if (mq.addEventListener) {
      mq.addEventListener('change', onChange);
    } else if (mq.addListener) {
      mq.addListener(onChange);
    }
  }
})();
</script>
"""

# ---------------------------------------------------------------------------
# Page-level orchestration
# ---------------------------------------------------------------------------


def render_details_page(data: ReportData, hints: dict[str, dict]) -> str:
    """The full listing for ``details.qmd``: every result, grouped by category."""
    if not data.results:
        return ""
    feature_index = FeatureStepIndex()
    dominant = dominant_feature_description(data.results)
    categories = group_by_category(data.results)
    parts: list[str] = []
    index = 0
    for category, items in sorted(categories.items()):
        label = category.replace("_", " ").title()
        parts.append(
            f'<div class="vip-cat-section"><h2 class="vip-cat-header">{_esc(label)}</h2>'
            f'<p class="vip-cat-counts">{_pluralize(len(items))} — '
            f"{_esc(_outcome_counts_summary(items))}</p>"
        )
        for item in items:
            parts.append(
                render_card(
                    item,
                    index=index,
                    feature_index=feature_index,
                    hints=hints,
                    dominant_description=dominant,
                )
            )
            index += 1
        parts.append("</div>")
    parts.append(CLIPBOARD_SCRIPT)
    parts.append(PRINT_EXPAND_SCRIPT)
    return "".join(parts)


def render_actionable_cards(data: ReportData, hints: dict[str, dict]) -> str:
    """Failures and skips in full — the part of a run a reader needs to act on (F6).

    Passes are represented only by the counts in ``render_products_table``
    and ``render_summary_table``; rendering every passed card here would
    just reproduce ``details.qmd`` on the page meant to be its short
    summary.
    """
    if not data.results:
        return ""
    actionable = [r for r in data.results if r.status in OUTCOME_ORDER]
    if not actionable:
        return "<p><em>No failures or skips — every check passed.</em></p>"
    feature_index = FeatureStepIndex()
    dominant = dominant_feature_description(data.results)
    parts: list[str] = []
    index = 0
    for status in OUTCOME_ORDER:
        group = [r for r in actionable if r.status == status]
        if not group:
            continue
        style = outcome_style(status)
        parts.append(
            f'<div class="vip-cat-section">'
            f'<h3 class="vip-cat-header" style="color:{style.color}">'
            f"{_esc(OUTCOME_LABELS[status])} ({len(group)})</h3>"
        )
        for item in group:
            parts.append(
                render_card(
                    item,
                    index=index,
                    feature_index=feature_index,
                    hints=hints,
                    dominant_description=dominant,
                )
            )
            index += 1
        parts.append("</div>")
    parts.append(CLIPBOARD_SCRIPT)
    parts.append(PRINT_EXPAND_SCRIPT)
    return "".join(parts)


def render_products_table(data: ReportData) -> str:
    """Products under test, with per-product pass/fail/skip counts (F7)."""
    configured = data.configured_products()
    if not configured:
        return "<p><em>No products configured. Set product URLs in <code>vip.toml</code>.</em></p>"
    rows = []
    for product in configured:
        name = _esc(product.name.replace("_", " ").title())
        url = _esc(product.url)
        version = _esc(product.version) if product.version else "—"
        items = results_for_product(data.results, product.name)
        if not items:
            results_cell = "no results recorded"
        else:
            results_cell = f"{_outcome_counts_summary(items)} ({_pluralize(len(items))})"
        rows.append(
            f"<tr><td>{name}</td><td>{url}</td><td>{version}</td><td>{_esc(results_cell)}</td></tr>"
        )
    return (
        "<table><thead><tr><th>Product</th><th>URL</th><th>Version</th>"
        "<th>Results</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_summary_table(data: ReportData) -> str:
    """The overall pass/fail/skip/status roll-up."""
    if data.total == 0:
        return "<p><em>No results found. Run <code>pytest</code> to generate results.</em></p>"
    status, status_class = (
        ("FAIL", "summary-status-fail")
        if data.failed
        else (
            "PASS",
            "summary-status-pass",
        )
    )
    return (
        "<table><tbody>"
        f"<tr><th>Total</th><td>{data.total}</td></tr>"
        f"<tr><th>Passed</th><td>{data.passed}</td></tr>"
        f"<tr><th>Failed</th><td>{data.failed}</td></tr>"
        f"<tr><th>Skipped</th><td>{data.skipped}</td></tr>"
        f'<tr><th>Status</th><td><span class="{status_class}">{status}</span></td></tr>'
        "</tbody></table>"
    )


# pytest's documented exit codes (https://docs.pytest.org/en/stable/reference/exit-codes.html).
_EXIT_STATUS_LABELS = {
    0: "OK — no failures",
    1: "tests were collected and run, but some failed",
    2: "run was interrupted by the user",
    3: "an internal error occurred",
    4: "pytest command line usage error",
    5: "no tests were collected",
}


def _cell(value: str | None) -> str:
    return _esc(value) if value is not None else "<em>not recorded</em>"


def render_provenance_table(data: ReportData) -> str:
    """VIP version, run duration, interpreter/platform, mode, exit status (F9).

    Every provenance field but ``exit_status`` is ``None`` on a
    ``results.json`` written before Phase 1 added them; each renders "not
    recorded" for that case rather than a fabricated value — see
    ``ReportData``'s own docstring for why that matters for an artifact a
    customer archives as evidence.
    """
    duration = (
        f"{data.run_duration_seconds:.1f}s" if data.run_duration_seconds is not None else None
    )
    mode = None if data.basic_mode is None else ("basic" if data.basic_mode else "full")
    exit_label = _EXIT_STATUS_LABELS.get(data.exit_status, "unrecognized exit code")
    rows = [
        ("VIP version", _cell(data.vip_version)),
        ("Run duration", _cell(duration)),
        ("Python", _cell(data.python_version)),
        ("Platform", _cell(data.platform)),
        ("Mode", _cell(mode)),
        ("Exit status", _esc(f"{data.exit_status} ({exit_label})")),
    ]
    body = "".join(f"<tr><th>{_esc(label)}</th><td>{value}</td></tr>" for label, value in rows)
    return f"<table><tbody>{body}</tbody></table>"
