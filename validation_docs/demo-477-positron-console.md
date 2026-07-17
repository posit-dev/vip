# fix(workbench): Positron console launch gate (#477)

*2026-07-17T18:46:10Z by Showboat 0.6.1*
<!-- showboat-id: 0213a95f-d688-4362-8af9-9f0e4a424b69 -->

Issue #477: test_launch_positron skipped with 'Positron console element not found ... selector may have changed or Positron may not be fully available', even though Positron was installed and reachable. Root cause (found by live diagnosis on dev.current, NOT selector drift): Positron on Workbench 2026+ opens to a Welcome page with NO auto-started console. The console panel (.positron-console) and its input/tab do not exist until a console session is STARTED and an interpreter is selected -- and interpreter discovery is asynchronous (~10s on a cold session). The old gate waited 30s for .positron-console on the Welcome page, where it can never appear, so it produced a false-negative skip. The same console-gated selectors also broke exec.py's _detect_ide and Positron readback.

Fix: a shared, idempotent ensure_positron_console(page) helper clicks 'Start New Console Session', polls the async interpreter quickpick (a single poll budget shared across discovery + render so total wait is bounded by timeout, not 2x), selects an interpreter, and waits for the console to render. It never raises -- both the row click and the Enter fallback are best-effort. positron_console_accessible calls it then asserts the console panel, skipping with an accurate reason (Start control unavailable / no interpreter resolved / console did not render) only when a console truly can't be started. _detect_ide now keys off .positron-variables (present even on the Welcome page). The existing CONSOLE_* selectors were correct and are unchanged.

```bash
grep -E 'START_CONSOLE_BUTTON|INTERPRETER_QUICKPICK_ROW =' src/vip_tests/workbench/pages/positron_session.py
```

```output
    START_CONSOLE_BUTTON = 'button[aria-label="Start New Console Session"]'
    # Interpreter rows in the quickpick opened by START_CONSOLE_BUTTON.
    INTERPRETER_QUICKPICK_ROW = (
```

```bash
grep -E 'def ensure_positron_console|def _detect_ide|VARIABLES_PANE\).count|return "positron"' src/vip_tests/workbench/exec.py
```

```output
def ensure_positron_console(page: Page, timeout: int = 45_000) -> bool:
def _detect_ide(page: Page) -> str:
        page.locator(PositronSession.VARIABLES_PANE).count() > 0
        return "positron"
```

```bash
grep -c 'ensure_positron_console' src/vip_tests/workbench/test_ide_launch.py
```

```output
3
```

```bash
env -u UV_PROJECT uv run --frozen --no-sync --project . pytest selftests/test_workbench_exec.py -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
73 passed
```

```bash
env -u UV_PROJECT uv run --frozen --no-sync --project . ruff check src/vip_tests/workbench/exec.py src/vip_tests/workbench/pages/positron_session.py src/vip_tests/workbench/test_ide_launch.py selftests/test_workbench_exec.py
```

```output
All checks passed!
```

Live validation on dev.current.posit.team (interactive browser auth; not re-runnable here). BEFORE: test_launch_positron[chromium] SKIPPED ('Positron console element not found ... may not be fully available'). AFTER this fix: 'test_launch_positron[chromium] ... PASSED' in a full 'vip verify --workbench-url https://dev.current.posit.team --interactive-auth --categories workbench -- -k test_launch_positron' run -- Positron launches, the console session starts, the Python 3.12 interpreter is discovered (~10s) and selected, the console renders, and the assertion passes.
