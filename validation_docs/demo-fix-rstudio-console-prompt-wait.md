# fix(workbench): raise ExecError with descriptive message when R console times out

*2026-06-12T00:00:00Z by Showboat 0.6.1*
<!-- showboat-id: bc8e2d1c-f53e-46b3-8b6e-d5643484260c -->

Fixes #275: when `rstudio_eval` times out waiting for its end marker in the
console output, it now raises `ExecError` with a message that explains the
likely cause — a startup script (e.g. an `.Rprofile` with an interactive
Acceptable-Usage-Policy prompt) blocking the console before it can accept
input. The happy path (no blocking prompt) is unchanged: the function types
into `INPUT`, presses Enter, then waits for the end marker in `OUTPUT` exactly
as before.

The broken approach from the original branch (waiting for `"> "` in
`OUTPUT_ELEMENT` before typing) has been removed. That check always timed out
on healthy consoles because the R prompt lives in the console INPUT gutter at
fresh startup, not in the output element. The fix is now entirely in the
timeout-catch path: `PlaywrightTimeoutError` from `expect(...).to_contain_text`
is caught and re-raised as `ExecError` with the descriptive message.

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
143 files already formatted
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
685 passed, 3 skipped, 20 warnings
```

```bash
uv run pytest src/vip_tests/ --collect-only -q 2>&1 | grep -E 'collected|deselected' | sed 's/ in [0-9.]*s//'
```

```output
6/113 tests collected (107 deselected)
```

```bash
grep -n 'ExecError\|PlaywrightTimeoutError\|OUTPUT_ELEMENT' src/vip_tests/workbench/exec.py
```

```output
24:from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
34:class ExecError(RuntimeError):
111:    Raises ExecError if either marker is absent in *text*.
115:        raise ExecError(f"Start marker not found in captured output (marker={start!r})")
118:        raise ExecError(f"End marker not found in captured output (marker={end!r})")
146:    for the end marker to appear before raising ExecError.
157:        ExecError: End marker did not appear within *timeout* — typically means
161:        PlaywrightTimeoutError: Console input was not visible within *timeout*.
175:    except PlaywrightTimeoutError as exc:
176:        raise ExecError(
390:    raise ExecError(
440:        ExecError: If the expression output cannot be captured.
```

