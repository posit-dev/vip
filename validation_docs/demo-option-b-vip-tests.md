# refactor: move tests/ to src/vip_tests/ (Option B)

*2026-03-26T00:13:13Z by Showboat 0.6.1*
<!-- showboat-id: 9f792148-c7c5-4127-be99-574953b0d2fb -->

Moved product tests from top-level tests/ to src/vip_tests/ to eliminate namespace collision and pytest import ambiguity when the package is installed. Updated all from tests. imports, pyproject.toml (hatch packages + testpaths), ruff src paths, CI workflows, and documentation.

```bash
uv run pytest src/vip_tests/ --collect-only --quiet 2>&1 | grep 'tests collected'
```

```output
76 tests collected in 0.09s
```

```bash
uv run pytest src/vip_tests/ --collect-only --quiet 2>&1 | grep 'tests collected' | sed 's/ in [0-9.]*s//'
```

```output
76 tests collected
```

```bash
uv run pytest selftests/ 2>&1 | grep -E '^=.*passed' | sed 's/ in [0-9.]*s//'
```

```output
======================== 95 passed, 2 warnings ========================
```

```bash
uv run ruff check src/ selftests/ examples/ && uv run ruff format --check src/ selftests/ examples/ && echo 'All checks passed'
```

```output
All checks passed!
89 files already formatted
All checks passed
```
