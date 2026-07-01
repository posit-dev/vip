# Design — #410: Better version gating

**Status:** Approved design (brainstorming) — ready for implementation plan
**Date:** 2026-06-30
**Issue:** posit-dev/vip#410
**Dispatch order:** AFTER #411 merges (parallel with #409)

## Problem

Version gating today is a single marker `@pytest.mark.min_version(product=, version=)`
handled in `src/vip/plugin.py:_maybe_skip_for_version`. Limitations:
- Minimum only — no behavior switching, no ranges.
- Runs **optimistically** when the version is unknown (`pc.version is None` → test runs),
  causing spurious failures.
- Naive `_version_tuple` parser (first `\d+` per dotted segment) — fragile on Posit
  calendar versions with suffixes (`2026.06.0-dev+123`, dailies, previews).
- Can only **skip**, never switch behavior. Gates at whole-test level, so it cannot express
  "click selector A on 2026.05+, selector B before" (the Workbench New Session dialog
  redesign case).

## Scope (from design chat)
**In:** behavior/selector switching per version · robust version parsing ·
unknown-version handling · "N/A" report status.
**Out (deprioritized):** `max_version` / version ranges.

## Key insight
VIP **already** separates selectors from tests: `src/vip_tests/workbench/pages/` holds
page-object selector classes (`Homepage`, `LoginPage`, `ConsolePaneSelectors`,
`RStudioSession`, ...) as flat class constants (they even mirror upstream e2e TS page
files). What is missing is a **version dimension** — the constants are static.

## Mechanism — versioned page-object classes via cumulative inheritance

Chosen over resolver-methods and a data registry. Decisive factor: with #409's Workbench
version matrix, a fixture picks the page object **once** (`get_homepage(version)`) and every
step downstream uses it — no `version` argument threaded through dozens of step defs.

UI changes are cumulative and forward, so a linear inheritance chain models product
evolution and each subclass holds **only the delta**:

```python
class Homepage:                       # oldest supported — full selector set
    POSIT_LOGO = "#posit-logo"
    NEW_SESSION_BUTTON = "#newSessionBtn"

class Homepage_2026_05(Homepage):     # shadcn redesign — override only what changed
    NEW_SESSION_BUTTON = "button:text-is('New Session')"
```

- A `get_<page>(version)` factory maps a detected version to the right class.
- No drift: each selector defined exactly once per version it changes in.
- Support window is **current + 1–2 back (2–3 live)**, so inheritance depth stays ~2–3.

### Behavior flows (not just selectors)
For flows that change (Escape vs `#modalCancelBtn`), use an `idp.py`-style **strategy dict
keyed by version range** (mirrors `_IDP_STRATEGIES`), resolved alongside the page object.

## Robust version parser
Replace `plugin.py:_version_tuple` with a real Posit calendar-version type:
`YYYY.MM.patch` plus `-dev` / `-daily` / `-preview` / `+build` suffixes, with correct
comparison and per-product scheme tolerance. Likely a small `src/vip/version.py`
(`ProductVersion`) used by both the gate marker and the page-object factory.

## Unknown-version policy
When a product version cannot be detected: **skip + mark N/A + emit a warning**
(consistent with the chosen N/A report status; safest — no spurious failures, gaps visible).

## Report status
Add a distinct **"N/A (version)"** status in `src/vip/reporting.py` and the Quarto
templates, separate from "skipped (unconfigured)", so version gaps are visible in reports.

## Dependencies
- **#411 first** (code-surface churn). **#409 Child B** consumes the versioned page objects.

## Acceptance criteria
- Versioned page-object classes + `get_<page>(version)` factory in `pages/`; volatile
  selectors version-resolved, stable ones inherited once.
- Behavior strategy dict keyed by version range for flow differences.
- `ProductVersion` parser handling calendar versions + suffixes; replaces `_version_tuple`.
- Unknown version → skip + N/A + warning.
- "N/A (version)" status distinct in report data model + Quarto output.
- Selftests cover parser edge cases, factory selection, and unknown-version handling.
- ruff + mypy clean; CLAUDE.md / `docs/test-architecture.md` updated for the version dimension.
