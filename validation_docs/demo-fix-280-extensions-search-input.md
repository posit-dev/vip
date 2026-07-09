# Fix #280: extensions search input Monaco selector

*2026-07-09T16:41:12Z by Showboat 0.6.1*
<!-- showboat-id: 63a88a0e-2b36-4496-b931-759dd9d23a86 -->

## Root cause

On Workbench 2026.04+, the VS Code / Positron extensions sidebar's search box
is rendered as a Monaco editor line (`div[data-uri='extensions:searchinput'] .view-line`),
not a plain `<input type='text'>`. The old selector, `.extensions-search-container
input[type='text']`, matches nothing, so `page.locator(...)` times out waiting
for visibility, and even when a matching element was found in older builds,
Playwright's `Locator.fill()` rejects Monaco's contenteditable-backed widget
because it isn't a native form control.

## Fix

- Updated `EXTENSIONS_SEARCH_INPUT` in both `vscode_session.py` and
  `positron_session.py` to point at the Monaco view-line selector.
- Reworked `_verify_extensions_panel` in `test_ide_extensions.py` to click the
  Monaco line to focus it, then drive real keystrokes via `page.keyboard`
  (select-all + backspace to clear the previous query, then type the new one)
  instead of calling `.fill()`.
- This is the same click + `page.keyboard.type()` pattern PR #402 used to fix
  the RStudio Ace console for issue #376 -- the established repo pattern for
  driving non-fillable Monaco/Ace editor widgets in Workbench IDEs.

## Step 2 (from the plan): confirm the blast radius

Exactly three hits are expected -- the two page-object definitions and the
single call site in `_verify_extensions_panel`. Confirmed below (against
the pre-fix codebase this grep matched the same three lines; only the RHS
values changed).

```bash
grep -rn --include='*.py' "EXTENSIONS_SEARCH_INPUT" src/
```

```output
src/vip_tests/workbench/test_ide_extensions.py:312:    extensions_input = page.locator(selectors.EXTENSIONS_SEARCH_INPUT)
src/vip_tests/workbench/pages/vscode_session.py:41:    EXTENSIONS_SEARCH_INPUT = "div[data-uri='extensions:searchinput'] .view-line"
src/vip_tests/workbench/pages/positron_session.py:43:    EXTENSIONS_SEARCH_INPUT = "div[data-uri='extensions:searchinput'] .view-line"
```

## Verification gate

Local `uv` invocations in this worktree inherit `UV_PROJECT` from the
workspace-level direnv config, which points at a sibling project
(`ptd/python-pulumi`) and silently re-roots dependency resolution away from
vip. `env -u UV_PROJECT` below undoes that so these commands actually run
against vip's own environment.

`selftests/test_load_engine.py` contains known timing-sensitive tests (see
CLAUDE.md); it is excluded from the run below to keep this demo
deterministic. It is untouched by this change -- only the three files
listed above were modified.

```bash
env -u UV_PROJECT uv run pytest selftests/ --ignore=selftests/test_load_engine.py -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
879 passed, 22 warnings
```

```bash
env -u UV_PROJECT uv run ruff check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

```bash
env -u UV_PROJECT uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
152 files already formatted
```

```bash
env -u UV_PROJECT uv run pytest src/vip_tests/workbench/ --collect-only -q 2>&1 | tail -3 | sed 's/ in [0-9.]*s//'
```

```output
  vip_cfg = load_config(config.getoption("--vip-config"))

no tests collected (35 deselected)
```

## Live validation status

**Pending.** There is no live Workbench 2026.04 environment available in
this session, so the Monaco selector and the click/keyboard-type flow have
not been exercised against a running IDE. This must be validated against a
real Workbench 2026.04+ deployment (VS Code and Positron sessions, extensions
panel) before this PR merges.
