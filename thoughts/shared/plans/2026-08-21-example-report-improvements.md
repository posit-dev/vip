# Example Validation Report — improvements

Branch: `example-report-improvements` (off `origin/main` @ ec848134)

The report is published publicly at https://posit-dev.github.io/vip/example-report/
and embedded in `website/src/pages/report.astro`. It is the customer-facing
showcase of what a VIP validation report looks like, so content quality on the
summary page matters more than anywhere else in the repo.

All findings below were confirmed against the **live published artifact**, not
just the source.

## Goal

One PR that removes the misplaced Connect System Checks dump, fixes the
content problems visible on the public page, de-duplicates the two Quarto
templates behind a testable rendering module, and repairs the workflow that
generates it.

## Findings to fix

### F0 — Connect System Checks section is out of place (the original ask)
`report/index.qmd:435-482` is the only product-specific, hand-rolled section on
an otherwise product-agnostic, results-driven page. It reads a side-channel
`connect_system_checks.json` no other part of the report knows about and renders
55 rows of raw shell output (`env`, `df -h`, `free -h`, `cat /etc/os-release`,
full `curl -Lsv` wire traces) — the bulk of a 362 KB page, with its own TOC entry.

It also publishes host internals. Connect's own masking caught
`CONNECT_BOOTSTRAP_SECRETKEY` and `X-Correlation-Id`, and
`test_system_checks.py` redacts license keys and job keys, but
`_DD_ROOT_GO_SESSION_ID=864620fa-1f0d-439b-9d18-0f267f7f41be` still shipped.
Guarding an arbitrary `env` dump with a regex allowlist is the wrong shape of
guarantee for a public page.

**Decision:** delete the section from `index.qmd`. Keep
`test_system_checks.py`, keep its redaction logic, keep
`connect_system_checks.json` as an uploaded CI artifact. Do not relocate it into
`details.qmd`.

### F1 — the failure demo is broken and its scaffolding is on the public page
`src/vip_tests/prerequisites/test_expected_failure.py` asserts Workbench *is*
configured. It was written when CI never configured Workbench; CI configures it
now, so the test **passes**. The live report shows a green card titled
*"Workbench server is reachable but not configured"*, described *"As a VIP
developer"*, from a file named `test_expected_failure.py`.

Meanwhile the only real FAIL is accidental:
`AssertionError: Test user 'testuser' (from 'testuser') not found in user list: ['__bootstrap_admin__']`
— the CI Connect container never creates `testuser`. The showcase's one failure
makes VIP look broken instead of showing VIP catching something.

**Decision (flag to Ian):** preserve the original intent — the example report
should demonstrate failure rendering — but make it honest:
- Provision `testuser` in the example-report workflow so the accidental Connect
  failure goes away.
- Rewrite the demo so it fails *reliably* and *by construction*, not as a
  side effect of Workbench config, and so its feature/scenario text reads
  sensibly to a customer and is plainly labelled as an intentional example.
- Give it a `troubleshooting.toml` entry so the hints block actually renders in
  the published example (see F11).

### F2 — the summary page shows raw pytest tracebacks
`details.qmd:320` renders `concise_error` up front with the traceback behind a
`<details>`. `index.qmd:362` renders `longrepr` only. The public summary
therefore shows `.venv/lib/python3.14/site-packages/_pytest/fixtures.py`, the
source of `call_fixture_func`, and fixture reprs. `concise_error` already exists
on `TestResult` and is already populated by the plugin.

### F3 — skips carry no reason
5 of 25 results on the live page are SKIP with nothing explaining why. A reader
cannot tell "not configured, benign" from "we could not check this".

The reason is available — pytest puts it in `report.longrepr` — but
`src/vip/plugin.py:1176` stores the stringified tuple
`('/Users/ianfloressiaca/.../test_load_engine.py', 255, 'Skipped: high-concurrency localhost loads are flaky on macOS CI runners')`,
absolute local paths included, and neither template displays it.

Add a parsed `skip_reason` to `TestResult`, populate it in the plugin, render it
on skip cards. Parsing it also stops absolute developer paths leaking into
`results.json`.

### F4 — `feature_description` is pure noise
"As a Posit Team administrator" renders on all 25 cards. It is the Gherkin user-
story line, identical everywhere. Drop it from the card, or use the Feature-level
description when it differs from the user story.

### F5 — `index.qmd` and `details.qmd` are ~80% copy-paste
~150 lines of byte-identical inline CSS in both, while `report/styles.css`
already exists and is already wired through `_quarto.yml`
(`format.html.css`). Plus duplicated `_get_feature`, `_get_steps`,
`_OUTCOME_STYLES`, `_PRODUCT_BADGE_CSS`, the `<param>` substitution, the card
renderer, and the clipboard script.

None of it is reachable by a test where it currently lives — `selftests/test_reporting.py`
covers `vip.reporting`, not the `.qmd` files.

Move CSS into `styles.css`; move card/section rendering into a new
`src/vip/report_html.py`; the templates become thin.

### F6 — the two pages show the same content
`index.qmd` groups by outcome then product; `details.qmd` groups by category.
Both list every card with full step lists. "Summary" is currently the longer
page. Make `index.qmd` an actual summary and let `details.qmd` be the full
listing.

### F7 — no per-product rollup
"Products Under Test" gives URL and version but no counts. For a validation
artifact "Connect: 6/7 passed" is the number the reader wants.

### F8 — marker coverage gaps
`_PRODUCT_BADGE_CSS` knows 5 markers; `pyproject.toml:172-189` registers 16.
`cross_product` tests land in an unstyled "Other" bucket. The IDE markers
(`rstudio`/`vscode`/`jupyter`/`positron`) never reach the report, so a Workbench
card does not say which IDE it exercised. `config_hygiene`, `performance` and
`slow` are invisible too.

### F9 — no provenance
No VIP version, no total run duration, no basic-vs-full mode, no host OS.
`ReportData.exit_status` is loaded by `load_results` and never displayed. For an
artifact a customer archives as evidence, the producing tool's version matters.

### F10 — not self-contained, not printable
`report/_output/` is a multi-file site with a 295 KB `search.json` for two pages.
No `embed-resources`, no print stylesheet. Customers archive and PDF these.

### F11 — troubleshooting hints cover 7 of 104 scenarios
`src/vip_tests/troubleshooting.toml` has 7 entries against 104 scenarios in 45
feature files, and one of the 7 is for the dead demo scenario. The hints block is
the report's best feature and almost never fires; the live failure gets no hint.
Add entries for the scenarios that appear in the example report plus the common
failure modes — judiciously, not all 104.

### F12 — workflow issues in `.github/workflows/example-report.yml`
- PM pinned to `ubuntu2204-2024.08.0` (line 151) while Connect and Workbench use
  `release`, so the public report advertises a two-year-old PM. The
  resolve-version step (line ~198) hardcodes the same string as its fallback.
  `packagemanager-smoke.yml:62` documents the repo convention: the bare
  `ubuntu2204` tag always resolves to the latest PM build. Use that.
- Workbench and PM have license-gate steps; `CONNECT_LICENSE` is used unguarded,
  so a missing Connect secret fails the whole job instead of degrading like the
  other two products.
- `pytest ... || true` (line ~295) cannot distinguish "tests failed" (wanted,
  the report should still render) from "pytest crashed" (should fail the job).
- Runs 8 of 45 feature files (25 of 104 scenarios) with nothing on the page
  saying it is a curated subset.
- `.gitignore:25` ignores `report/report/` and `report/report/results.json`
  exists in the primary checkout — something writes to the wrong nested path and
  it has been papered over rather than fixed.
- `website/src/pages/report.astro:16` still says "against Connect and Package
  Manager"; Workbench was added since.

### F13 — nits
- "1 tests" — no pluralisation (`index.qmd:303`).
- `import re as _re` inside the card loop in both templates
  (`index.qmd:314`, `details.qmd:271`).
- Emoji-only status in the system-checks table with no text alternative, and no
  `scope`/`caption` on the table (moot once F0 lands).
- Per-file `format: html: code-fold: true` front matter duplicating `_quarto.yml`
  and inert anyway, since every chunk is `#| echo: false`.

## Constraints

- Stay close to existing patterns; F5 is the one explicitly-sanctioned refactor.
- `report/styles.css` is already the shared-CSS home — extend it, do not invent
  a new mechanism.
- `vip.reporting` stays the data layer. New HTML rendering goes in a sibling
  module so it is unit-testable from `selftests/`.
- Templates must still render when optional inputs are missing
  (`troubleshooting.toml` absent, no results, product not configured) — that is
  existing behaviour and is covered by `selftests/test_cli_report.py`.
- `feature_file_for_nodeid` / `troubleshooting_path` must keep working both from
  a source checkout and an installed wheel.
- Update `docs/reporting.md` and any other affected `.md`.

## Phases

- [ ] Phase 1 — data layer: `skip_reason` + provenance in `vip/reporting.py`
      and `vip/plugin.py`, with selftests.
- [ ] Phase 2 — rendering: new `vip/report_html.py`, CSS into `styles.css`,
      slim templates, and all content fixes (F0, F2, F4, F6, F7, F8, F13).
      Depends on Phase 1.
- [ ] Phase 3 — workflow, demo test, troubleshooting entries, docs
      (F1, F11, F12, F10).
