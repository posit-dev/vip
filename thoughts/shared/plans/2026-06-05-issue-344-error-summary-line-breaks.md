# Plan for issue #344: Preserve line breaks in `error_summary` so `failures.json` is readable

## Context

`failures.json` is the machine-readable artifact a developer or CI pipeline reaches for when a `vip verify` run fails. Today, the `error_summary` field is a single physical line of text — even when the underlying error contained dozens of meaningful log lines (build output, task output, traceback context). The reporter writes the file via `cat report/failures.json | jq -r '.failures[0].error_summary'` and then has to scroll horizontally or post-process to figure out what went wrong. The companion `feature` field, by contrast, preserves its original line breaks and is comfortable to read.

Issue #344 calls out the asymmetry directly: the user expects `error_summary` to be readable in the same way `feature` is. Fixing this is a low-risk quality-of-life improvement to the failure-reporting surface that the rest of the team (and the Quarto report) already consumes.

The proximate cause lives in `src/vip/plugin.py::_extract_exception_info` — when pytest's `longrepr` contains a multi-line exception message (continuation `E   ...` lines, common for Connect deployment errors that embed `--- Task output ---` blobs), the function joins those lines with a single space (line ~610). Every embedded newline that the upstream system intentionally produced is squashed. The downstream `_format_concise_error` and the eventual `error_summary` payload inherit that flattened message verbatim.

## Architecture

The change is contained to a single subsystem — the VIP pytest plugin's failure-formatting helpers — and does not touch any client, fixture, feature file, or report template. The data flow is:

```
pytest TestReport.longrepr (multi-line E   prefix lines)
  → src/vip/plugin.py::_extract_exception_info  (returns exc_type, exc_message)
  → src/vip/plugin.py::_format_concise_error    (returns the concise_error string)
  → results.json (concise_error)
  → failures.json (error_summary = concise_error or longrepr[:500])
```

Two design choices need to be made up front and locked in by the plan, because they shape what consumers (terminal printer, JSON file, Quarto report) see:

1. **Where to preserve newlines.** Preserve them inside `exc_message` returned by `_extract_exception_info`. Keep `_format_concise_error` agnostic about layout — it just interpolates whatever message it gets. This keeps the boundary clean: extraction does fidelity, formatting does framing.
2. **What separator to use when joining E-line continuations.** Replace the current `" "` join with `"\n"`, then strip trailing whitespace. This restores the original visual structure of the upstream message for any consumer that respects newlines (jq, bat, the Quarto report, an editor opening the JSON). Single-line consumers (e.g. a one-line terminal print) can collapse with `.replace("\n", " ")` at the call site if they need to — that is a smaller, more local concern than the global flattening we do today.

The terminal display path (`report.longrepr = _format_concise_error(...)` at line ~814) is the one place that does want a single-line rendering for the `FAILED` line in pytest's terminal output. The plan calls out the need to flatten newlines at that specific call site so the terminal experience does not regress.

The `failures.json` consumer is fine with multi-line strings — JSON encodes `\n` natively, and `jq -r` and the existing Quarto template both render them as real line breaks.

## Components

**src/vip/**
- `plugin.py` — change `_extract_exception_info` so the join in the E-line continuation block uses `"\n"` instead of `" "`, and trims trailing blank lines. Adjust the terminal-rendering call site (around line 814) to collapse newlines back to spaces so pytest's one-line `FAILED ...` summary stays compact. Leave `concise_error` (which feeds `results.json` and `failures.json`) multi-line.
- No changes to any other file under `src/vip/` — the `_format_concise_error` signature and behavior stay the same, and downstream callers (`pytest_sessionfinish`, the report writer) are already string-passthroughs.

**selftests/**
- `test_plugin.py` — extend the existing `test_failures_json_uses_concise_error` block (or add a sibling test) with a fixture that raises an exception whose message contains literal newlines, and assert that the resulting `error_summary` in `failures.json` contains `\n` between the original lines. Add a second assertion verifying the terminal `FAILED` line for that test still renders on a single line (no embedded newlines), guarding the regression call-out above.
- Update `test_failures_json_uses_concise_error`'s upper-bound length check (currently `< 200`) only if the new newline characters push it over — likely fine, but the implementer must verify and adjust the bound in the same PR if needed.

**report/**
- No changes needed. `report/details.qmd` already renders text fields verbatim; multi-line strings will display with line breaks because Quarto markdown respects them in preformatted blocks.

## Verification

A reviewer can confirm the change end-to-end with the following commands.

1. Lint and selftests must pass:

   ```bash
   uv run ruff check src/ selftests/
   uv run ruff format --check src/ selftests/
   uv run pytest selftests/test_plugin.py -v
   ```

   Success: green ruff output and the new newline-preservation tests pass alongside the existing concise-error tests.

2. Manual check against a real failure. With a `vip.toml` configured for any deployment that has at least one expected-failing test (or by deliberately misconfiguring a URL):

   ```bash
   uv run vip verify --config vip.toml --categories prerequisites -- -k connect
   cat report/failures.json | jq -r '.failures[0].error_summary' | bat --no-pager
   ```

   Success: the printed output has multiple visible lines, matching the original structure of the upstream error log, comparable to the readability of `jq -r '.failures[0].feature'` in the issue's "easy to read" example.

3. Terminal regression check:

   ```bash
   uv run vip verify --config vip.toml --categories prerequisites
   ```

   Success: the pytest `FAILED ...` summary lines are still single-line — no wrapping or `\n` characters bleeding into the terminal — confirming the call-site flatten in `pytest_runtest_logreport` works.

## Open questions

- **UNCONFIRMED**: Should we also limit the multi-line `error_summary` to a maximum number of *lines* (e.g. 50) on top of the existing 500-character truncation that applies when `concise_error` is `None`? Embedded build logs can be hundreds of lines. Proposal: keep the current behavior (no per-line cap) for the first iteration since the upstream message is already pre-shaped by pytest's traceback formatter, and revisit if real failures produce uncomfortably long `error_summary` blobs.
- **UNCONFIRMED**: Does any downstream tool (e.g. an internal dashboard, a Slack notifier) depend on `error_summary` being a single line? A repository-wide grep for `error_summary` shows only the plugin and selftests, but external consumers in posit-dev/* or internal tooling may exist. The implementer should ask in the PR description before merging.
- Whether to expand `_extract_exception_info`'s top-level fallback (line ~631, `return "UnknownError", longrepr.strip()[:200]`) is **out of this plan** — it already preserves newlines because `.strip()` does not collapse internal whitespace. No change needed there.

## Out of scope

- Changing the Quarto report (`report/details.qmd`) layout. The existing rendering already respects newlines; nothing else needs adjusting.
- Adjusting the 500-character truncation in `failures.json` for the fallback case where `concise_error` is `None`. That is a separate consideration tracked elsewhere.
- Refactoring `_extract_exception_info` to use a structured object instead of a `(str, str)` tuple. The current shape is sufficient for this fix; a broader refactor would expand the diff and risk for no user-visible benefit.
- Modifying the terminal verbose path (`--vip-verbose`) — it already shows full tracebacks and is unaffected by this change.
- Touching the `feature` and `scenario` fields in `failures.json`; the issue is specifically about `error_summary`.
