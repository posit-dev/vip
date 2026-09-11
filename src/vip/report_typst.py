"""Typst rendering for the VIP report PDF.

``vip.report_content`` is the format-neutral layer. This module is its second
backend: it turns the same content ``vip.report_html`` renders as HTML into
Typst markup, which ``report/vip-report.qmd`` emits as a raw ``{=typst}``
block for Quarto to compile into ``vip-report.pdf``.

Why a second backend rather than letting Quarto render the existing pages to
PDF: ``index.qmd`` and ``details.qmd`` hand Quarto raw HTML through
``IPython.display.HTML()``. Pandoc rescues a plain ``<table>`` when it targets
Typst and drops everything else to the object's repr, so a native PDF of those
pages prints ``<IPython.core.display.HTML object>`` where every result card,
traceback, and troubleshooting hint should be. Typst markup is the content
Quarto can actually compile — and the PDF being a native Quarto render is the
point: the report demonstrates Quarto, not a headless browser.

The PDF must look like the HTML report, not merely carry the same facts. The
faces are the report's own — Source Sans 3 (the face under the HTML report's
cosmo theme) and Source Code Pro, both vendored in ``report/fonts/`` so the
render is identical on a laptop, in CI, and on an air-gapped host. Sizes,
colors, and the card/badge/table vocabulary mirror ``report/styles.css``;
shared color values live in ``report_content`` and are drift-guarded by
``selftests/test_report_content.py``.

Escaping is a security property here for the same reason it is in
``report_html``: the PDF is published (https://posit-dev.github.io/vip/) and
embeds test titles, error text, and hints taken straight from test output and
Gherkin source. Every dynamic value goes into Typst as a **string literal**
via ``_lit`` and is passed to a Typst function positionally. Typst renders a
string verbatim, so markup characters in test output (``#``, ``*``, ``_``,
``@``, ``$``) cannot escape into the document as formatting or as a function
call. Do not switch a value to Typst content syntax (``[...]``) to get
formatting — wrap the ``_lit`` in a styling function instead.
"""

from __future__ import annotations

import textwrap

from vip.report_content import (
    COVERAGE_LABELS,
    COVERAGE_STYLE_KEY,
    NOT_RECORDED,
    OUTCOME_LABELS,
    OUTCOME_ORDER,
    SECONDARY_BADGE_BACKGROUND,
    SECONDARY_BADGE_BORDER,
    TRACEABILITY_CAVEAT,
    TRACEABILITY_RENDER_FAILURE,
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

# Monospaced runs (tracebacks, nodeids) carry tokens far longer than the text
# column — an absolute path, a parametrized nodeid. Typst breaks a line at
# spaces only, so those runs are wrapped in Python first: at spaces where
# possible, mid-token only when a single token exceeds the whole width. At 8pt
# Source Code Pro (0.6 em advance) the card's inner column fits ~97 columns.
_MONO_WRAP = 96


def _lit(value: str) -> str:
    """``value`` as a Typst string literal, safe to drop into markup.

    Backslash first: escaping it after the quote would double-escape the
    backslash this function itself introduced.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\r", "").replace("\t", "    ")
    return f'"{escaped}"'


def _wrap(text: str, width: int) -> str:
    """Wrap monospaced ``text`` at ``width`` columns, preserving line structure.

    Wraps at spaces like a browser would; a single token longer than the whole
    width is split mid-token as a last resort. A continuation line keeps its
    original indentation plus four spaces, so a wrapped traceback still reads
    as one frame.
    """
    lines: list[str] = []
    for line in text.split("\n"):
        if len(line) <= width:
            lines.append(line)
            continue
        indent = line[: len(line) - len(line.lstrip(" "))]
        pieces = textwrap.wrap(
            line,
            width=width,
            subsequent_indent=indent + "    ",
            break_long_words=True,
            break_on_hyphens=False,
        )
        lines.extend(pieces or [""])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Typst source builders
# ---------------------------------------------------------------------------


def _call(name: str, *args: str) -> str:
    return f"{name}({', '.join(args)})"


def _text(value: str, **options: str) -> str:
    """A Typst ``text()`` call carrying ``value`` as an escaped string literal.

    Option values are Typst source, not user data — every caller passes a
    literal from this module. Only ``value`` comes from the report.
    """
    opts = "".join(f"{key.replace('_', '-')}: {val}, " for key, val in options.items())
    return f"text({opts}{_lit(value)})"


def _block(
    body: str, *, above: str = "4pt", below: str = "4pt", inset: str = "", sticky: bool = False
) -> str:
    """Wrap ``body`` (already-built Typst markup) in a spaced block.

    ``sticky`` attaches the block to whatever follows it, so a section header
    is never left widowed at the bottom of a page while its first card starts
    the next one.
    """
    pad = f", inset: {inset}" if inset else ""
    stick = ", sticky: true" if sticky else ""
    return f"#block(above: {above}, below: {below}{pad}{stick})[{body}]\n"


def _tuple(values: list[str]) -> str:
    """A Typst array of the given source expressions. One element needs its comma."""
    body = ", ".join(values)
    return f"({body},)" if len(values) == 1 else f"({body})"


# Typst helpers for the report's own vocabulary: the outcome chip, the two
# badge shapes, the card, and the tables. Each mirrors a rule in
# report/styles.css, so a change to one belongs in the other. Emitted once at
# the top of the document, along with the body/link/heading defaults.
PREAMBLE = f"""
#set text(font: "Source Sans 3", size: 10pt, fill: rgb("#212529"))
#set par(leading: 0.5em)
#show link: it => underline(offset: 1.5pt, stroke: 0.5pt + rgb("#2f6db4"),
  text(fill: rgb("#2f6db4"), it))
#show heading.where(level: 1): set text(size: 18pt, weight: 700, fill: rgb("#1f2937"))
#show heading.where(level: 2): it => block(
  width: 100%, above: 18pt, below: 10pt,
  stroke: (bottom: 0.5pt + rgb("#dee2e6")), inset: (bottom: 5pt),
  text(size: 14pt, weight: 700, fill: rgb("#1f2937"), it.body),
)
#let vip-chip(label, fg, bg) = box(
  fill: rgb(bg), radius: 3pt, inset: (x: 5pt, y: 2pt), outset: (y: 2.5pt),
  text(size: 7pt, weight: "bold", fill: rgb(fg), tracking: 0.3pt, label),
)
#let vip-pill(label, bg) = box(
  fill: rgb(bg), radius: 8pt, inset: (x: 6.5pt, y: 2pt), outset: (y: 2.5pt),
  text(size: 7pt, weight: "bold", fill: white, label),
)
#let vip-tag(label) = box(
  fill: rgb("{SECONDARY_BADGE_BACKGROUND}"),
  stroke: 0.5pt + rgb("{SECONDARY_BADGE_BORDER}"),
  radius: 8pt, inset: (x: 6.5pt, y: 2pt), outset: (y: 2.5pt),
  text(size: 7pt, weight: "bold", fill: rgb("#4b5563"), label),
)
#let vip-card(accent, breakable, body) = block(
  width: 100%, above: 8pt, below: 8pt, breakable: breakable,
  radius: (rest: 4pt), fill: rgb("#fefefe"),
  inset: (left: 12pt, right: 12pt, top: 9pt, bottom: 9pt),
  stroke: (left: 3pt + rgb(accent), rest: 0.75pt + rgb("#e5e7eb")),
  body,
)
#let vip-mono(size, color, body) = text(
  size: size, fill: rgb(color), font: "Source Code Pro", body,
)
#let vip-note(fill-color, border, body) = block(
  width: 100%, above: 6pt, below: 6pt, radius: 4pt, inset: 10pt,
  breakable: false,
  fill: rgb(fill-color), stroke: 0.5pt + rgb(border), body,
)
#let vip-table(columns, cells) = block(above: 6pt, below: 12pt, table(
  columns: columns,
  inset: (x: 8pt, y: 6pt),
  stroke: (x, y) => (bottom: 0.5pt + rgb("#e5e7eb")),
  ..cells,
))
"""


def outcome_chip(status: str) -> str:
    """The PASS/FAIL/SKIP/N-A chip that opens a card."""
    style = outcome_style(status)
    return _call("vip-chip", _lit(style.label), _lit(style.color), _lit(style.background))


def _badge_typst(badge: Badge, primary: bool) -> str:
    if primary:
        return _call("vip-pill", _lit(badge.label), _lit(badge.color))
    return _call("vip-tag", _lit(badge.label))


def product_badges(item: TestResult) -> str:
    """Every primary badge on ``item``, followed by any secondary (IDE/slow) badges."""
    badges = [_badge_typst(b, primary=True) for b in primary_badges_for(item)]
    badges += [_badge_typst(b, primary=False) for b in secondary_badges_for(item.markers)]
    return "".join(f"#{b} " for b in badges)


def steps_block(steps: list[str]) -> str:
    """The Gherkin procedure for a scenario.

    The HTML report hides this behind a ``<details>``; a PDF has nothing to
    click, and the print stylesheet already expands it on paper, so it is
    always visible here.
    """
    if not steps:
        return ""
    label = _text("Test procedure", size="8.5pt", weight='"bold"', fill='rgb("#6b7280")')
    out = _block(f"#{label}", above="6pt", below="3pt")
    for step in steps:
        line = _call("vip-mono", "8pt", _lit("#374151"), _lit(f"› {step}"))
        out += _block(f"#{line}", above="1.5pt", below="1.5pt", inset="(left: 10pt)")
    return out


def description_block(item: TestResult, dominant: str | None) -> str:
    """The card's feature-description line, when it differs from the run's dominant one."""
    line = description_line(item, dominant)
    if not line:
        return ""
    styled = _text(line, size="9pt", style='"italic"', fill='rgb("#6b7280")')
    return _block(f"#{styled}", above="3pt", below="3pt")


def skip_reason_block(item: TestResult) -> str:
    """The explanation on a skip card, with any version-gate detail beneath it (F3)."""
    explanation, detail = skip_reason_parts(item)
    if not explanation:
        return ""
    styled = _text(explanation, size="9pt", fill='rgb("#92400e")')
    out = _block(f"#{styled}", above="3pt", below="2pt")
    if detail:
        quiet = _call("vip-mono", "8pt", _lit("#92400e"), _lit(detail))
        out += _block(f"#{quiet}", above="0pt", below="3pt")
    return out


def error_block(item: TestResult) -> str:
    """The concise error, then the full traceback.

    The HTML report collapses the traceback behind a ``<details>`` because it
    can run to dozens of frames. The PDF is the archived evidence copy, and
    the print stylesheet already expands the same section on paper, so the
    traceback is always rendered here.
    """
    if item.outcome != "failed":
        return ""
    parts = []
    if item.concise_error:
        styled = _text(item.concise_error, size="9.5pt", weight="600", fill='rgb("#dc2626")')
        parts.append(_block(f"#{styled}", above="6pt", below="3pt"))
    if item.longrepr:
        body = _lit(_wrap(item.longrepr, _MONO_WRAP))
        parts.append(
            f'#block(width: 100%, above: 5pt, below: 5pt, fill: rgb("#1e1e1e"), '
            f"radius: 4pt, inset: 10pt, breakable: true)[\n"
            f'  #vip-mono(8pt, "#d4d4d4", {body})\n'
            f"]\n"
        )
    return "".join(parts)


def _hint_list(label: str, entries: list[str], numbered: bool) -> str:
    """A labelled bullet or numbered list of hint entries.

    ``list()``/``enum()`` take their items as arguments, so the items are
    comma-separated — Typst reads a missing comma as the end of the call and
    fails to compile.
    """
    marker = "enum" if numbered else "list"
    items = ",\n".join(f"  {marker}.item[#{_text(entry, size='9pt')}]" for entry in entries)
    heading = _text(label, size="9pt", weight='"bold"')
    return (
        f"#block(above: 5pt, below: 2pt)[#{heading}]\n"
        f"#{marker}(spacing: 5pt, tight: true, indent: 6pt, body-indent: 6pt,\n{items},\n)\n"
    )


def hints_block(item: TestResult, hints: dict[str, dict]) -> str:
    """Troubleshooting hints for a failed card, keyed by ``scenario_title``."""
    if item.outcome != "failed" or not item.scenario_title:
        return ""
    hint = hints.get(item.scenario_title) or {}
    if not hint:
        return ""
    parts: list[str] = []
    if hint.get("likely_causes"):
        parts.append(_hint_list("Likely causes:", list(hint["likely_causes"]), numbered=False))
    if hint.get("suggested_steps"):
        steps = list(hint["suggested_steps"])
        parts.append(_hint_list("Suggested next steps:", steps, numbered=True))
    if hint.get("docs_url"):
        url = hint["docs_url"]
        label = _text("Documentation: ", size="9pt", weight='"bold"')
        target = _text(url, size="8.5pt")
        parts.append(f"#block(above: 5pt, below: 2pt)[#{label}#link({_lit(url)})[#{target}]]\n")
    if not parts:
        return ""
    body = "".join(parts)
    return f'#vip-note("#fffbeb", "#fbbf24")[\n  #set text(fill: rgb("#92400e"))\n{body}]\n'


def render_card(
    item: TestResult,
    *,
    feature_index: FeatureStepIndex,
    hints: dict[str, dict],
    dominant_description: str | None,
) -> str:
    """Render one test result as a self-contained card.

    Takes no ``index``: the HTML card needs one to seed its copy-button
    element id, and a PDF has no copy button.

    A card with a traceback or hints can outgrow a page, so it must be
    allowed to break across one; every other card is a few lines tall and
    stays whole (the PDF's version of the print stylesheet's
    ``break-inside: avoid``), because a page boundary through a short card
    orphans a single line on the next page.
    """
    style = outcome_style(item.status)
    title = _text(display_title(item), size="10pt", weight="600", fill='rgb("#1f2937")')
    header = f"#{outcome_chip(item.status)} #{title} {product_badges(item)}"
    meta = _wrap(f"{item.nodeid}  {item.duration:.2f}s", _MONO_WRAP)
    meta_line = _call("vip-mono", "8pt", _lit("#9ca3af"), _lit(meta))
    body = (
        f"{header}\n"
        f"{description_block(item, dominant_description)}"
        f"{skip_reason_block(item)}"
        f"{_block(f'#{meta_line}', above='3pt', below='2pt')}"
        f"{steps_block(feature_index.steps_for(item))}"
        f"{error_block(item)}"
        f"{hints_block(item, hints)}"
    )
    breakable = "true" if (item.longrepr or hints.get(item.scenario_title or "")) else "false"
    return f"#vip-card({_lit(style.color)}, {breakable})[\n{body}]\n"


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

_LABEL_STYLE = {"size": "9pt", "weight": "700", "fill": 'rgb("#1f2937")'}


def _table(columns: str, headers: list[str], rows: list[list[str]]) -> str:
    """A ``vip-table`` call: ``columns`` is a Typst track list, cells are built here."""
    cells: list[str] = []
    if headers:
        header_cells = ", ".join(_text(h, **_LABEL_STYLE) for h in headers)
        cells.append(f"table.header({header_cells})")
    for row in rows:
        cells.extend(row)
    return f"#vip-table({columns}, {_tuple(cells)})\n"


def _kv_table(rows: list[tuple[str, str]]) -> str:
    """A two-column label/value table (Summary, Provenance), labels bold."""
    cells = [[_text(label, **_LABEL_STYLE), value_markup] for label, value_markup in rows]
    return _table("(150pt, 1fr)", [], cells)


def render_products_table(data: ReportData) -> str:
    """Products under test, with per-product pass/fail/skip counts (F7)."""
    configured = data.configured_products()
    if not configured:
        return _paragraph("No products configured. Set product URLs in vip.toml.", italic=True)
    rows = []
    for product in configured:
        items = results_for_product(data.results, product.name)
        if items:
            results_cell = f"{outcome_counts_summary(items)} ({pluralize(len(items))})"
        else:
            results_cell = "no results recorded"
        rows.append(
            [
                _text(category_label(product.name), size="9pt"),
                _call("vip-mono", "8.5pt", _lit("#374151"), _lit(product.url)),
                _text(product.version or "—", size="9pt"),
                _text(results_cell, size="9pt"),
            ]
        )
    return _table("(auto, 1fr, auto, auto)", ["Product", "URL", "Version", "Results"], rows)


def render_summary_table(data: ReportData) -> str:
    """The overall pass/fail/skip/status roll-up."""
    if data.total == 0:
        return _paragraph("No results found. Run pytest to generate results.", italic=True)
    status = summary_status(data)
    color = "#dc2626" if data.failed else "#16a34a"
    rows: list[tuple[str, str]] = [
        ("Total", _text(str(data.total), size="9pt")),
        ("Passed", _text(str(data.passed), size="9pt")),
        ("Failed", _text(str(data.failed), size="9pt")),
        ("Skipped", _text(str(data.skipped), size="9pt")),
        ("Status", _text(status, size="9.5pt", weight="700", fill=f'rgb("{color}")')),
    ]
    return _kv_table(rows)


def render_provenance_table(data: ReportData) -> str:
    """VIP version, run duration, interpreter/platform, mode, exit status (F9).

    A row whose value ``report_content.provenance_rows`` reports as ``None``
    renders "not recorded" (italic, like the HTML report's ``<em>``) rather
    than a fabricated value.
    """
    rows: list[tuple[str, str]] = []
    for label, value in provenance_rows(data):
        if value is None:
            cell = _text(NOT_RECORDED, size="9pt", style='"italic"', fill='rgb("#6b7280")')
        else:
            cell = _text(value, size="9pt")
        rows.append((label, cell))
    return _kv_table(rows)


# ---------------------------------------------------------------------------
# Document-level orchestration
# ---------------------------------------------------------------------------


def _paragraph(
    value: str,
    *,
    italic: bool = False,
    fill: str | None = None,
    weight: str | None = None,
) -> str:
    options = {"size": "10pt"}
    if italic:
        options["style"] = '"italic"'
    if fill is not None:
        options["fill"] = fill
    if weight is not None:
        options["weight"] = weight
    return _block(f"#{_text(value, **options)}", above="6pt", below="6pt")


def _heading(text: str, level: int) -> str:
    return f"#heading(level: {level}, {_lit(text)})\n"


def _labelled_line(label: str, value: str) -> str:
    """A "Deployment: Acme Corp" line with a bold label, as on index.qmd."""
    bold = _text(f"{label}: ", size="10pt", weight="700")
    return _block(f"#{bold}#{_text(value, size='10pt')}", above="3pt", below="3pt")


def _section_header(label: str, count_line: str, color: str | None = None) -> str:
    options = {"size": "12.5pt", "weight": '"bold"'}
    options["fill"] = f'rgb("{color}")' if color else 'rgb("#1f2937")'
    out = _block(f"#{_text(label, **options)}", above="14pt", below="2pt", sticky=True)
    if count_line:
        counts = _text(count_line, size="8.5pt", fill='rgb("#6b7280")')
        out += _block(f"#{counts}", above="0pt", below="6pt", sticky=True)
    return out


def render_actionable_cards(data: ReportData, hints: dict[str, dict]) -> str:
    """Failures and skips in full — the part of a run a reader needs to act on (F6).

    Passes are represented only by the counts in ``render_products_table``
    and ``render_summary_table``; the full listing follows in its own section.
    """
    if not data.results:
        return ""
    actionable = [r for r in data.results if r.status in OUTCOME_ORDER]
    if not actionable:
        return _paragraph("No failures or skips — every check passed.", italic=True)
    feature_index = FeatureStepIndex()
    dominant = dominant_feature_description(data.results)
    parts: list[str] = []
    for status in OUTCOME_ORDER:
        group = [r for r in actionable if r.status == status]
        if not group:
            continue
        parts.append(
            _section_header(
                f"{OUTCOME_LABELS[status]} ({len(group)})", "", outcome_style(status).color
            )
        )
        parts += [
            render_card(
                item, feature_index=feature_index, hints=hints, dominant_description=dominant
            )
            for item in group
        ]
    return "".join(parts)


def render_details(data: ReportData, hints: dict[str, dict]) -> str:
    """The full listing: every result, grouped by category."""
    if not data.results:
        return ""
    feature_index = FeatureStepIndex()
    dominant = dominant_feature_description(data.results)
    parts: list[str] = []
    for category, items in sorted(group_by_category(data.results).items()):
        parts.append(
            _section_header(
                category_label(category),
                f"{pluralize(len(items))} — {outcome_counts_summary(items)}",
            )
        )
        parts += [
            render_card(
                item, feature_index=feature_index, hints=hints, dominant_description=dominant
            )
            for item in items
        ]
    return "".join(parts)


def _stacked(parts: list[str]) -> str:
    """Several Typst expressions as one table cell, separated by line breaks.

    A table cell must be a single expression, so multi-line content needs a
    content block rather than concatenated ``#`` calls -- which is what
    ``text(...)#block(...)`` produced, and Typst rejected.
    """
    if len(parts) == 1:
        return parts[0]
    return "[" + "#linebreak()".join(f"#{part}" for part in parts) + "]"


def render_traceability(matrix) -> str:  # noqa: ANN001 - TraceabilityMatrix
    """The compliance traceability section as Typst markup.

    Every customer-supplied value passes through ``_lit`` (this module's
    standing invariant). A control list is authored outside VIP, so a
    description containing ``#``, ``*`` or ``$`` is live Typst markup
    otherwise -- and these are the first fully customer-authored strings to
    reach this backend.
    """
    parts = [
        _paragraph(TRACEABILITY_CAVEAT, italic=True, fill='rgb("#6b7280")'),
        _kv_table(
            [
                (label, _text(value, size="9pt"))
                for label, value in traceability_summary_rows(matrix)
            ]
        ),
    ]
    for warning in traceability_warnings(matrix):
        parts.append(_paragraph(warning, fill='rgb("#dc2626")', weight='"bold"'))

    rows = []
    for row in control_rows(matrix):
        style = outcome_style(COVERAGE_STYLE_KEY[row.coverage])
        control_parts = [_text(row.control_id, size="9pt")]
        if row.reference:
            control_parts.append(_text(row.reference, size="8pt", fill='rgb("#6b7280")'))
        if row.risk:
            control_parts.append(_text(f"risk: {row.risk}", size="8pt", fill='rgb("#6b7280")'))
        if row.scenarios:
            evidence = _stacked(
                [_text(f"{t} - {s} at {w}", size="8.5pt") for t, s, w in row.scenarios]
            )
        else:
            evidence = _text("no tagged scenario", size="8.5pt", style='"italic"')
        rows.append(
            [
                _stacked(control_parts),
                _text(row.description, size="9pt"),
                # vip-chip, not vip-pill: the HTML edition renders dark text on
                # a pale fill (outcome_badge_html), and vip-pill is a saturated
                # fill with white text. The two editions must match.
                _call(
                    "vip-chip",
                    _lit(COVERAGE_LABELS[row.coverage]),
                    _lit(style.color),
                    _lit(style.background),
                ),
                evidence,
            ]
        )
    parts.append(
        _table(
            "(auto, 1fr, auto, 1.2fr)",
            ["Control", "Description", "Coverage", "Evidence"],
            rows,
        )
    )
    return "".join(parts)


def render_document(data: ReportData, hints: dict[str, dict], matrix=None, trace_error=None) -> str:  # noqa: ANN001
    """The whole PDF body, preamble included, ready to emit as a ``{=typst}`` block.

    ``matrix`` is a ``vip.traceability.TraceabilityMatrix`` or ``None``. When
    it is ``None`` -- every run without a control list, which is nearly all of
    them -- the output is byte-identical to before the section existed.

    ``trace_error`` names why the section could not be built at all (a
    missing/malformed control list, a results checksum mismatch). It renders
    through ``_paragraph``, which routes the text through ``_text`` to
    ``_lit``. An exception message is arbitrary text, and ``_lit`` escapes
    the characters that could terminate the string literal early -- the
    quote in particular, plus backslash -- so the message lands as inert
    literal text inside the quotes rather than breaking out into live
    markup. A dropped section is invisible to a regulated reader, so this
    is a visible marker in both editions rather than a silent skip.
    """
    # The error branch and the matrix branch emit the same heading, so a
    # reader of the PDF sees the section start either way instead of the
    # section silently disappearing.
    if trace_error:
        trace_section = _heading("Compliance Traceability", 2) + _paragraph(
            TRACEABILITY_RENDER_FAILURE.format(error=trace_error)
        )
    elif matrix is not None:
        trace_section = _heading("Compliance Traceability", 2) + render_traceability(matrix)
    else:
        trace_section = ""

    if data.total == 0:
        empty = PREAMBLE + _paragraph("No results found. Run vip verify to generate results.")
        # The HTML cell renders the section whenever a control list is set,
        # including over an empty results file, where the matrix is all gaps
        # and manual controls. Returning early here would drop it from the
        # PDF alone and split the two editions on exactly the run a reader is
        # most likely to misread.
        return empty + trace_section
    parts = [
        PREAMBLE,
        _heading("VIP Validation Report", 1),
        _labelled_line("Deployment", data.deployment_name),
        _labelled_line("Generated", data.generated_at_display),
        _heading("Products Under Test", 2),
        render_products_table(data),
        _heading("Summary", 2),
        render_summary_table(data),
        _heading("Provenance", 2),
        render_provenance_table(data),
        trace_section,
        _heading("Failures & Skips", 2),
        _paragraph(
            "Every check that did not pass, in full. Passing checks are counted above, "
            "and every check appears in Detailed Results below."
        ),
        render_actionable_cards(data, hints),
        "#pagebreak()\n",
        _heading("Detailed Results", 2),
        render_details(data, hints),
    ]
    return "".join(parts)
