"""HTML rendering for the VIP Quarto report.

``vip.report_content`` is the format-neutral layer: titles, outcome and
marker styling, grouping, skip wording, provenance rows. This module is one
of its two backends. It turns that content into the HTML fragments
``report/index.qmd`` and ``report/details.qmd`` hand to
``IPython.display.HTML()``. ``vip.report_typst`` is the other backend, and
renders the same content as Typst markup for the PDF.

Nothing here decides *what* the reader sees — only what markup says it. A
change to wording, grouping, or color belongs in ``report_content`` so both
outputs get it.

Escaping is a security property here, not a style choice: the report is
published publicly (https://posit-dev.github.io/vip/example-report/) and
embeds test titles, error messages, and troubleshooting hints taken straight
from test output and Gherkin source. Every value interpolated into the HTML
this module returns goes through ``html.escape`` — do not add an
interpolation that skips it.
"""

from __future__ import annotations

from html import escape as _esc

from vip.report_content import (
    COVERAGE_LABELS,
    COVERAGE_STYLE_KEY,
    NOT_RECORDED,
    OUTCOME_LABELS,
    OUTCOME_ORDER,
    TRACEABILITY_CAVEAT,
    Badge,
    FeatureStepIndex,
    category_label,
    control_rows,
    description_line,
    display_title,
    dominant_feature_description,
    group_by_category,
    outcome_counts_summary,
    outcome_style,
    pluralize,
    primary_badges_for,
    provenance_rows,
    results_for_product,
    secondary_badges_for,
    skip_reason_parts,
    summary_status,
    traceability_summary_rows,
    traceability_warnings,
)
from vip.reporting import ReportData, TestResult


def outcome_badge_html(status: str) -> str:
    """The PASS/FAIL/SKIP/N-A chip that opens a card."""
    style = outcome_style(status)
    return (
        f'<span class="vip-badge" style="color:{style.color};background:{style.background}">'
        f"{_esc(style.label)}</span>"
    )


def _badge_html(badge: Badge) -> str:
    return f'<span class="{badge.css_class}">{_esc(badge.label)}</span>'


def secondary_badges_html(markers: list[str]) -> str:
    return "".join(_badge_html(badge) for badge in secondary_badges_for(markers))


def product_badges_html(item: TestResult) -> str:
    """Every primary badge present in ``item.markers`` (may be more than one),
    followed by any secondary (IDE/slow) badges."""
    primary = "".join(_badge_html(badge) for badge in primary_badges_for(item))
    return primary + secondary_badges_html(item.markers)


def steps_html(steps: list[str]) -> str:
    if not steps:
        return ""
    items = "".join(f"<li>{_esc(s)}</li>" for s in steps)
    return (
        f'<details class="vip-test-steps"><summary>Test procedure</summary>'
        f'<ul class="vip-step-list">{items}</ul></details>'
    )


def description_html(item: TestResult, dominant: str | None) -> str:
    """The card's feature-description line, when it differs from the run's dominant one."""
    line = description_line(item, dominant)
    if not line:
        return ""
    return f'<div class="vip-test-description">{_esc(line)}</div>'


def skip_reason_html(item: TestResult) -> str:
    """The explanation on a skip card, with any version-gate detail beneath it (F3).

    See ``report_content.skip_reason_parts`` for why an ``na_version`` card
    reads differently from an ordinary skip.
    """
    explanation, detail = skip_reason_parts(item)
    if not explanation:
        return ""
    parts = [_esc(explanation)]
    if detail:
        parts.append(f'<span class="vip-skip-detail">{_esc(detail)}</span>')
    return f'<div class="vip-skip-reason">{"".join(parts)}</div>'


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
        label = category_label(category)
        parts.append(
            f'<div class="vip-cat-section"><h2 class="vip-cat-header">{_esc(label)}</h2>'
            f'<p class="vip-cat-counts">{pluralize(len(items))} — '
            f"{_esc(outcome_counts_summary(items))}</p>"
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
            results_cell = f"{outcome_counts_summary(items)} ({pluralize(len(items))})"
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
    status = summary_status(data)
    status_class = "summary-status-fail" if data.failed else "summary-status-pass"
    return (
        "<table><tbody>"
        f"<tr><th>Total</th><td>{data.total}</td></tr>"
        f"<tr><th>Passed</th><td>{data.passed}</td></tr>"
        f"<tr><th>Failed</th><td>{data.failed}</td></tr>"
        f"<tr><th>Skipped</th><td>{data.skipped}</td></tr>"
        f'<tr><th>Status</th><td><span class="{status_class}">{status}</span></td></tr>'
        "</tbody></table>"
    )


def _cell(value: str | None) -> str:
    return _esc(value) if value is not None else f"<em>{_esc(NOT_RECORDED)}</em>"


def render_provenance_table(data: ReportData) -> str:
    """VIP version, run duration, interpreter/platform, mode, exit status (F9).

    A row whose value ``report_content.provenance_rows`` reports as ``None``
    renders "not recorded" rather than a fabricated value — see that
    function's docstring for why that matters for an artifact a customer
    archives as evidence.
    """
    body = "".join(
        f"<tr><th>{_esc(label)}</th><td>{_cell(value)}</td></tr>"
        for label, value in provenance_rows(data)
    )
    return f"<table><tbody>{body}</tbody></table>"


def render_traceability(matrix) -> str:  # noqa: ANN001 - vip.traceability.TraceabilityMatrix
    """The compliance traceability section: summary counts, then one row per control.

    Every customer-supplied value goes through ``_esc``. A control list is
    authored outside VIP entirely, so its descriptions and references are the
    first fully untrusted text this backend renders.
    """
    summary = "".join(
        f"<tr><th>{_esc(label)}</th><td>{_esc(value)}</td></tr>"
        for label, value in traceability_summary_rows(matrix)
    )
    parts = [
        f"<p class='trace-caveat'>{_esc(TRACEABILITY_CAVEAT)}</p>",
        f"<table><tbody>{summary}</tbody></table>",
    ]
    for warning in traceability_warnings(matrix):
        parts.append(f"<p class='trace-warning'><strong>{_esc(warning)}</strong></p>")

    rows = []
    for row in control_rows(matrix):
        style = outcome_style(COVERAGE_STYLE_KEY[row.coverage])
        badge = (
            f"<span class='badge' style='color:{style.color};"
            f"background:{style.background}'>{_esc(COVERAGE_LABELS[row.coverage])}</span>"
        )
        if row.scenarios:
            evidence = "<br>".join(
                f"{_esc(title)} &mdash; {_esc(status)} at {_esc(when)}"
                for title, status, when in row.scenarios
            )
        else:
            evidence = "<em>no tagged scenario</em>"
        reference = f"<br><small>{_esc(row.reference)}</small>" if row.reference else ""
        rows.append(
            f"<tr><td><code>{_esc(row.control_id)}</code>{reference}</td>"
            f"<td>{_esc(row.description)}</td><td>{badge}</td><td>{evidence}</td></tr>"
        )
    header = "<tr><th>Control</th><th>Description</th><th>Coverage</th><th>Evidence</th></tr>"
    parts.append(f"<table><thead>{header}</thead><tbody>{''.join(rows)}</tbody></table>")
    return "".join(parts)
