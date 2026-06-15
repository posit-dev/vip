# fix(workbench): IDE-aware git-ops readback (#386)

*2026-06-15T20:01:05Z by Showboat 0.6.1*
<!-- showboat-id: e3eddf95-ae3d-4ff9-b214-48427f2cd42c -->

## Problem (issue #386)

Workbench git-ops tests (#363) only passed for RStudio. `terminal_run` runs a shell command, redirects output to a temp file, and reads it back via a DOM console. The readback was broken for VS Code and Positron, so all their clone/branch/commit/push scenarios timed out.

Live diagnosis on a staging Workbench (and the selectors in posit-dev/positron/test/e2e) pinned the real causes:

- The integrated **terminal executes commands fine**; the xterm widget is **canvas-rendered**, so its text is NOT in the DOM (no scraping).
- The old `positron_eval_*` used wrong console selectors; `vscode_eval` waited on a Python Interactive Window a fresh session never opens.
- VS Code Web runs in **Mac keybinding mode**; `code` is not on PATH.

## Fix — route the readback by detected IDE

- **RStudio**: R console eval (unchanged).
- **Positron**: console eval with the real selectors (`.console-instance[style*='z-index: auto']`, `.console-input`, read `div span`), waiting for the interpreter to be input-ready.
- **VS Code**: open the temp file in the Monaco editor (Command Palette -> 'File: Open File'), dismiss the workspace-trust dialog, and read `.editor-instance .view-lines`.

Also scaled `_TIMEOUT_GIT_NETWORK`/`_TIMEOUT_IDE_READY` by VIP_TIMEOUT_SCALE (were hard-coded, undermining slow-deployment runs).

## Live validation (staging Workbench)

- **VS Code `test_clone_vscode`: PASS end-to-end** (clone -> editor readback found the done-marker -> file_exists confirmed the dir).
- **Positron console readback: PASS** (isolated probe read a terminal-written file via the console). The git-ops Positron scenario still auto-skips when the Positron console doesn't finish loading (slow-launch flakiness, tracked in #388) — by design, it skips rather than errors.

Selftests below are Playwright-free and cover the IDE-detection + routing logic.

### Lint + format

```bash
uv run --no-sync ruff check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

```bash
uv run --no-sync ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
154 files already formatted
```

### Readback routing selftests

```bash
uv run --no-sync pytest 'selftests/test_workbench_exec.py::TestDetectIde' 'selftests/test_workbench_exec.py::TestFileExistsRouting' 'selftests/test_workbench_exec.py::TestReadFileRouting' -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
14 passed
```

### Full workbench.exec selftest module

```bash
uv run --no-sync pytest selftests/test_workbench_exec.py -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
48 passed
```
