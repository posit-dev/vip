"""Render VIP test results as self-contained HTML.

Shared by the Quarto report templates and the Shiny app so that both
produce identical styled output.
"""

from __future__ import annotations

from html import escape as _esc
from pathlib import Path

from vip.gherkin import parse_feature_file
from vip.reporting import ReportData, TestResult

# ---------------------------------------------------------------------------
# Style constants (same palette as the Quarto report)
# ---------------------------------------------------------------------------

_OUTCOME_STYLES: dict[str, tuple[str, str, str]] = {
    "passed": ("PASS", "#16a34a", "#dcfce7"),
    "failed": ("FAIL", "#dc2626", "#fecaca"),
    "skipped": ("SKIP", "#6b7280", "#e5e7eb"),
}

_BORDER_COLORS: dict[str, str] = {
    "passed": "#16a34a",
    "failed": "#dc2626",
    "skipped": "#d1d5db",
}

_CSS = """\
<style>
.vip-report { font-family: system-ui, -apple-system, sans-serif; color: #1f2937; }
.vip-summary-table { border-collapse: collapse; margin-bottom: 1.5rem; }
.vip-summary-table th, .vip-summary-table td {
  text-align: left; padding: 0.375rem 1rem; border-bottom: 1px solid #e5e7eb;
}
.vip-summary-table th { font-weight: 600; color: #4b5563; }
.vip-product-table { border-collapse: collapse; margin-bottom: 1.5rem; width: 100%; }
.vip-product-table th, .vip-product-table td {
  text-align: left; padding: 0.375rem 0.75rem; border-bottom: 1px solid #e5e7eb;
}
.vip-product-table th { font-weight: 600; color: #4b5563; background: #f9fafb; }
.vip-cat-section { margin-bottom: 2rem; }
.vip-cat-header {
  font-size: 1.25rem; font-weight: 700; margin: 0 0 0.25rem; color: #1f2937;
}
.vip-cat-counts { font-size: 0.8125rem; color: #6b7280; margin-bottom: 0.75rem; }
.vip-test-card {
  border: 1px solid #e5e7eb; border-left: 4px solid #d1d5db;
  border-radius: 6px; padding: 0.75rem 1rem; margin-bottom: 0.5rem; background: #fefefe;
}
.vip-test-header { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.vip-test-scenario { font-weight: 600; font-size: 0.9375rem; color: #1f2937; }
.vip-badge {
  display: inline-block; font-size: 0.6875rem; font-weight: 700;
  padding: 0.1rem 0.4rem; border-radius: 3px;
  text-transform: uppercase; letter-spacing: 0.03em;
}
.vip-test-meta {
  font-size: 0.75rem; color: #9ca3af; font-family: monospace; margin-top: 0.125rem;
}
.vip-test-steps { margin-top: 0.375rem; }
.vip-test-steps summary {
  cursor: pointer; font-size: 0.8125rem; font-weight: 600;
  color: #6b7280; padding: 0.25rem 0;
}
.vip-test-steps summary:hover { color: #374151; }
.vip-step-list { margin: 0.25rem 0 0 1.25rem; padding: 0; list-style: none; }
.vip-step-list li {
  font-size: 0.8125rem; font-family: monospace; color: #374151; line-height: 1.6;
}
.vip-step-list li::before { content: "› "; color: #9ca3af; }
.vip-fail-details { margin-top: 0.5rem; margin-bottom: 0.5rem; }
.vip-fail-details summary {
  cursor: pointer; font-weight: 600; font-size: 0.8125rem;
  color: #6b7280; padding: 0.25rem 0;
}
.vip-fail-details summary:hover { color: #1f2937; }
.vip-fail-error-wrap { position: relative; margin-top: 0.375rem; }
.vip-fail-error {
  background: #1e1e1e; color: #d4d4d4; font-size: 0.8125rem; line-height: 1.5;
  padding: 1rem; border-radius: 4px; overflow-x: auto; margin: 0;
  white-space: pre-wrap; word-break: break-word;
}
.vip-copy-btn {
  position: absolute; top: 0.5rem; right: 0.5rem;
  background: rgba(255,255,255,0.1); color: rgba(255,255,255,0.7);
  border: 1px solid rgba(255,255,255,0.2); border-radius: 4px;
  padding: 0.2rem 0.5rem; font-size: 0.75rem; font-family: inherit;
  cursor: pointer; transition: background 0.15s, color 0.15s; z-index: 1;
}
.vip-copy-btn:hover { background: rgba(255,255,255,0.2); color: #fff; }
.vip-fail-hints {
  background: #fffbeb; border: 1px solid #fbbf24; border-radius: 4px;
  padding: 0.875rem 1rem; font-size: 0.875rem; color: #92400e; margin-top: 0.5rem;
}
.vip-fail-hints ul, .vip-fail-hints ol {
  margin: 0.25rem 0 0.75rem 1.25rem; padding: 0;
}
.vip-fail-hints li { margin-bottom: 0.25rem; }
.vip-fail-hints p { margin: 0.25rem 0; }
.vip-fail-hints a { color: #92400e; text-decoration: underline; }
</style>
"""

_COPY_SCRIPT = """\
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

# ---------------------------------------------------------------------------
# Feature file helpers
# ---------------------------------------------------------------------------


def _build_feature_cache(results: list[TestResult], project_root: Path | None) -> dict[str, dict]:
    """Pre-parse all referenced .feature files and return a cache dict."""
    cache: dict[str, dict] = {}
    if project_root is None:
        return cache
    for r in results:
        py_file = r.nodeid.split("::")[0] if "::" in r.nodeid else r.nodeid
        feature_file = py_file.rsplit(".", 1)[0] + ".feature"
        if feature_file in cache:
            continue
        p = project_root / feature_file
        if p.exists():
            cache[feature_file] = parse_feature_file(p)
        else:
            cache[feature_file] = {}
    return cache


def _get_steps(item: TestResult, cache: dict[str, dict]) -> list[str]:
    py_file = item.nodeid.split("::")[0] if "::" in item.nodeid else item.nodeid
    feature_file = py_file.rsplit(".", 1)[0] + ".feature"
    feature = cache.get(feature_file)
    if not feature or not feature.get("scenarios") or not item.scenario_title:
        return []
    for sc in feature["scenarios"]:
        if sc["title"] == item.scenario_title and sc.get("steps"):
            return sc["steps"]
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_report_html(
    data: ReportData,
    *,
    troubleshooting: dict[str, dict] | None = None,
    project_root: Path | None = None,
) -> str:
    """Return self-contained HTML for a VIP test report.

    Parameters
    ----------
    data:
        Parsed test results from ``load_results()``.
    troubleshooting:
        Optional dict from ``load_troubleshooting()``, keyed by scenario title.
    project_root:
        Root of the VIP project.  When provided, ``.feature`` files are
        resolved relative to this path so that BDD steps can be displayed.
    """
    if data.total == 0:
        return '<div class="vip-report"><p>No test results found.</p></div>'

    hints = troubleshooting or {}
    feature_cache = _build_feature_cache(data.results, project_root)
    parts: list[str] = [_CSS, '<div class="vip-report">']

    # --- header ---
    status = "PASS" if data.failed == 0 else "FAIL"
    status_color = "#16a34a" if status == "PASS" else "#dc2626"
    parts.append(
        f"<p><strong>Deployment:</strong> {_esc(data.deployment_name)}"
        f" &nbsp;|&nbsp; <strong>Generated:</strong> {_esc(data.generated_at_display)}"
        f' &nbsp;|&nbsp; <strong>Status:</strong> <span style="color:{status_color}">'
        f"<strong>{status}</strong></span></p>"
    )

    # --- products table ---
    configured = data.configured_products()
    if configured:
        parts.append('<table class="vip-product-table">')
        parts.append("<tr><th>Product</th><th>URL</th><th>Version</th></tr>")
        for p in configured:
            name = p.name.replace("_", " ").title()
            ver = _esc(p.version) if p.version else "—"
            parts.append(f"<tr><td>{_esc(name)}</td><td>{_esc(p.url)}</td><td>{ver}</td></tr>")
        parts.append("</table>")

    # --- summary table ---
    parts.append('<table class="vip-summary-table">')
    parts.append("<tr><th>Metric</th><th>Count</th></tr>")
    for label, value in [
        ("Total", data.total),
        ("Passed", data.passed),
        ("Failed", data.failed),
        ("Skipped", data.skipped),
    ]:
        parts.append(f"<tr><td>{label}</td><td>{value}</td></tr>")
    parts.append("</table>")

    # --- results by category ---
    categories = data.by_category()
    error_idx = 0
    for cat, items in sorted(categories.items()):
        cat_label = cat.replace("_", " ").title()
        cat_passed = sum(1 for i in items if i.outcome == "passed")
        cat_failed = sum(1 for i in items if i.outcome == "failed")
        cat_skipped = sum(1 for i in items if i.outcome == "skipped")

        counts = []
        if cat_passed:
            counts.append(f"{cat_passed} passed")
        if cat_failed:
            counts.append(f"{cat_failed} failed")
        if cat_skipped:
            counts.append(f"{cat_skipped} skipped")

        parts.append(
            f'<div class="vip-cat-section">'
            f'<h3 class="vip-cat-header">{_esc(cat_label)}</h3>'
            f'<p class="vip-cat-counts">{len(items)} tests — {", ".join(counts)}</p>'
        )

        for item in items:
            label, fg, badge_bg = _OUTCOME_STYLES.get(item.outcome, ("?", "#6b7280", "#e5e7eb"))
            border_color = _BORDER_COLORS.get(item.outcome, "#d1d5db")
            title = (
                _esc(item.scenario_title)
                if item.scenario_title
                else _esc(item.nodeid.split("::")[-1] if "::" in item.nodeid else item.nodeid)
            )
            nodeid = _esc(item.nodeid)
            duration = f"{item.duration:.2f}s"
            badge = (
                f'<span class="vip-badge" style="color:{fg};background:{badge_bg}">{label}</span>'
            )

            # BDD steps
            steps = _get_steps(item, feature_cache)
            steps_html = ""
            if steps:
                step_items = "".join(f"<li>{_esc(s)}</li>" for s in steps)
                steps_html = (
                    f'<details class="vip-test-steps">'
                    f"<summary>Test procedure</summary>"
                    f'<ul class="vip-step-list">{step_items}</ul>'
                    f"</details>"
                )

            # Error traceback
            error_html = ""
            if item.outcome == "failed" and item.longrepr:
                error_id = f"vip-err-{error_idx}"
                error_idx += 1
                error_html = (
                    f'<details class="vip-fail-details">'
                    f"<summary>Error traceback</summary>"
                    f'<div class="vip-fail-error-wrap">'
                    f'<button class="vip-copy-btn" data-target="{error_id}"'
                    f' title="Copy to clipboard">Copy</button>'
                    f'<pre id="{error_id}" class="vip-fail-error">'
                    f"{_esc(item.longrepr)}</pre>"
                    f"</div></details>"
                )

            # Troubleshooting hints
            hints_html = ""
            if item.outcome == "failed":
                hint = hints.get(item.scenario_title, {}) if item.scenario_title else {}
                if hint:
                    hint_parts: list[str] = []
                    if hint.get("likely_causes"):
                        hint_parts.append("<strong>Likely causes:</strong><ul>")
                        for cause in hint["likely_causes"]:
                            hint_parts.append(f"<li>{_esc(cause)}</li>")
                        hint_parts.append("</ul>")
                    if hint.get("suggested_steps"):
                        hint_parts.append("<strong>Suggested next steps:</strong><ol>")
                        for step in hint["suggested_steps"]:
                            hint_parts.append(f"<li>{_esc(step)}</li>")
                        hint_parts.append("</ol>")
                    if hint.get("docs_url"):
                        url = _esc(hint["docs_url"])
                        hint_parts.append(
                            f"<p><strong>Documentation:</strong> "
                            f'<a href="{url}" target="_blank" rel="noopener">{url}</a></p>'
                        )
                    if hint_parts:
                        hints_html = f'<div class="vip-fail-hints">{"".join(hint_parts)}</div>'

            parts.append(
                f'<div class="vip-test-card" style="border-left-color:{border_color}">'
                f'<div class="vip-test-header">{badge}'
                f'<span class="vip-test-scenario">{title}</span></div>'
                f'<div class="vip-test-meta">{nodeid} · {duration}</div>'
                f"{steps_html}{error_html}{hints_html}"
                f"</div>"
            )

        parts.append("</div>")

    parts.append("</div>")
    parts.append(_COPY_SCRIPT)
    return "\n".join(parts)
