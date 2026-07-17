# Fix: report review follow-ups

*2026-07-17T18:02:34Z by Showboat 0.6.1*
<!-- showboat-id: dee1ae11-c1c4-4dcb-98e1-6c227e4037dd -->

Follow-ups from code review on PR #487: the bundled-template refresh now skips identical files and prints a notice listing any existing templates it overwrites; a missing quarto binary produces a clear error instead of a traceback; the importlib.resources guard covers OSError but no longer swallows copy failures (an unwritable destination now surfaces instead of silently rendering stale templates); and a selftest pins the pyproject force-include block to cli._REPORT_TEMPLATE_FILES so the two lists cannot drift. Run the report selftests, which cover all of the above:

```bash
uv run pytest selftests/test_cli_report.py -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
17 passed
```

Lint and format checks (ruff pinned to the CI version):

```bash
uvx ruff@0.15.0 check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

```bash
uvx ruff@0.15.0 format --check src/ src/vip_tests/ selftests/ examples/ 2>&1 | tail -1
```

```output
160 files already formatted
```
