# refactor: move tests/ to src/vip_tests/ (Option B)

*2026-03-25T23:43:53Z by Showboat 0.6.1*
<!-- showboat-id: 19299671-864c-4c27-b88c-db878554259d -->

Moved product tests from top-level tests/ to src/vip_tests/ to avoid namespace collision and pytest import ambiguity when the package is installed. Updated all from tests. imports, pyproject.toml (hatch packages + testpaths), ruff src paths, CI workflows, and documentation.

```bash
uv run pytest src/vip_tests/ --collect-only --quiet 2>&1 | tail -3
```

```output
src/vip_tests/workbench/test_sessions.py::test_session_suspend_resume[chromium]

76 tests collected in 0.10s
```

```bash
uv run pytest selftests/ 2>&1 | tail -2
```

```output
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 95 passed, 2 warnings in 0.64s ========================
```

```bash
uv run --with 'ruff==0.15.0' ruff check src/ selftests/ examples/ && uv run --with 'ruff==0.15.0' ruff format --check src/ selftests/ examples/ && echo 'All checks passed'
```

```output
All checks passed!
89 files already formatted
All checks passed
```
