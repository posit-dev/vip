# fix(auth): headless auth no longer crashes on unreachable Workbench

*2026-04-20T22:32:02Z by Showboat 0.6.1*
<!-- showboat-id: 1d026eb0-2f62-43e1-aabf-40d254f1da95 -->

Issue #171: when `vip verify --headless-auth` reaches `_authenticate_workbench()` and the Workbench URL is unreachable (ERR_CONNECTION_REFUSED, mixed-content redirect, etc.), Playwright raised an uncaught error that killed the pytest session with `INTERNALERROR`.

This change wraps the `page.goto(workbench_url)` + `wait_for_load_state` calls in a try/except for `PlaywrightError`, matching the existing non-fatal pattern already used when the SSO redirect chain times out (lines 608-611). The warning names the URL and explains what to check, and Connect tests continue to run.

### New regression test

The test exercises `_authenticate_workbench()` directly with a mock Playwright page whose `page.goto()` raises `PlaywrightError('net::ERR_CONNECTION_REFUSED ...')` — the exact failure reported in the issue. Before the fix this propagated out; after the fix it prints a user-friendly warning naming the URL and returns cleanly.

```bash
uv run pytest selftests/test_auth.py::TestAuthenticateWorkbench -v 2>&1 | grep -E 'PASSED|FAILED|ERROR' | sed 's/ in [0-9.]*s//'
```

```output
selftests/test_auth.py::TestAuthenticateWorkbench::test_playwright_error_on_goto_is_non_fatal PASSED [100%]
```

### Full selftest suite

All 270 selftests pass, confirming the change has no regressions elsewhere.

```bash
uv run pytest selftests/ -q 2>&1 | grep -E '[0-9]+ passed' | sed 's/ in [0-9.]*s//'
```

```output
270 passed, 6 warnings
```

### Lint + format

CI pins ruff 0.15.0 and checks `src/`, `src/vip_tests/`, `selftests/`, `examples/` — all pass.

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

```bash
uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
101 files already formatted
```
