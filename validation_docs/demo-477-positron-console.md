# fix(workbench): Positron console launch gate (#477)

*2026-07-17T18:26:48Z by Showboat 0.6.1*
<!-- showboat-id: e19d3e43-916c-452b-b411-4a16b4eba96d -->

Issue #477: test_launch_positron skipped with 'Positron console element not found ... selector may have changed or Positron may not be fully available', even though Positron was installed and reachable. Root cause (found by live diagnosis on dev.current, NOT selector drift): Positron on Workbench 2026+ opens to a Welcome page with NO auto-started console. The console panel (.positron-console) and its input/tab do not exist until a console session is STARTED and an interpreter is selected -- and interpreter discovery is asynchronous (~10s on a cold session). The old gate waited 30s for .positron-console on the Welcome page, where it can never appear, so it produced a false-negative skip. The same console-gated selectors also broke exec.py's _detect_ide and Positron readback.

Fix: a shared, idempotent ensure_positron_console(page) helper clicks 'Start New Console Session', polls the async interpreter quickpick, selects an interpreter, and waits for the console to render. positron_console_accessible calls it then asserts the console panel (skipping with an ACCURATE reason only if no interpreter resolves). _detect_ide now keys off .positron-variables (present even on the Welcome page) so detection no longer depends on a running console. The existing CONSOLE_* selectors were correct and are unchanged.

```bash
grep -nE 'START_CONSOLE_BUTTON|INTERPRETER_QUICKPICK_ROW' src/vip_tests/workbench/pages/positron_session.py
```

```output
32:    START_CONSOLE_BUTTON = 'button[aria-label="Start New Console Session"]'
33:    # Interpreter rows in the quickpick opened by START_CONSOLE_BUTTON.
36:    INTERPRETER_QUICKPICK_ROW = (
```

```bash
grep -nE 'def ensure_positron_console|VARIABLES_PANE|def _detect_ide|return "positron"' src/vip_tests/workbench/exec.py
```

```output
258:def ensure_positron_console(page: Page, timeout: int = 45_000) -> bool:
617:def _detect_ide(page: Page) -> str:
630:        page.locator(PositronSession.VARIABLES_PANE).count() > 0
633:        return "positron"
```

```bash
grep -nE 'ensure_positron_console|pytest.skip' src/vip_tests/workbench/test_ide_launch.py | head
```

```output
30:from vip_tests.workbench.exec import ensure_positron_console, rstudio_eval
202:    """Best-effort cancel of the New Session dialog, then ``pytest.skip``.
221:    pytest.skip(reason)
284:        pytest.skip(reason)
406:        pytest.skip("No notebook kernel cards available in JupyterLab launcher")
437:        pytest.skip(
454:    ``ensure_positron_console`` clicks "Start New Console Session", waits for the
459:    if not ensure_positron_console(page, timeout=TIMEOUT_IDE_LOAD):
460:        pytest.skip(
```

```bash
env -u UV_PROJECT uv run --frozen --no-sync --project . pytest selftests/test_workbench_exec.py -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
71 passed
```

```bash
env -u UV_PROJECT uv run --frozen --no-sync --project . ruff check src/vip_tests/workbench/exec.py src/vip_tests/workbench/pages/positron_session.py src/vip_tests/workbench/test_ide_launch.py selftests/test_workbench_exec.py
```

```output
All checks passed!
```

Live validation on dev.current.posit.team (interactive browser auth; not re-runnable here). BEFORE: test_launch_positron[chromium] SKIPPED ('Positron console element not found ... may not be fully available'). AFTER this fix: 'test_launch_positron[chromium] ... PASSED' in a full 'vip verify --workbench-url https://dev.current.posit.team --interactive-auth --categories workbench -- -k test_launch_positron' run -- Positron launches, the console session starts, the Python 3.12 interpreter is discovered (~10s) and selected, the console renders, and the assertion passes.
