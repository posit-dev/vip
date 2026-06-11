# fix(workbench): wait for R console prompt before typing in launch test

*2026-06-11T16:01:06Z by Showboat 0.6.1*
<!-- showboat-id: bc8e2d1c-f53e-46b3-8b6e-d5643484260c -->

Fixes #275: rstudio_eval in exec.py now waits for the standard R prompt ('> ') in the console output element before typing. If the prompt does not appear within the timeout, an ExecError is raised with a message pointing to a blocking .Rprofile. The change is in src/vip_tests/workbench/exec.py only — one import added and ~15 lines added to rstudio_eval.

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
grep -n 'reach a ready prompt\|startup script\|OUTPUT_ELEMENT\|PlaywrightTimeoutError' src/vip_tests/workbench/exec.py
```

```output
24:from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
159:            typically means a startup script (e.g. an ``.Rprofile`` with an
161:        PlaywrightTimeoutError: Console input was not visible within *timeout*.
170:    # before typing.  If a startup script (e.g. an .Rprofile with an
174:    console_output_element = page.locator(ConsolePaneSelectors.OUTPUT_ELEMENT)
177:    except PlaywrightTimeoutError as exc:
179:            "R console did not reach a ready prompt — a startup script "
```
