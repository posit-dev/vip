# Update requests dependency to 2.33.0

*2026-03-25T23:01:46Z by Showboat 0.6.1*
<!-- showboat-id: 0309217a-f4b3-4dc9-bd72-a60d63f5bd5d -->

Updated the requests dependency from 2.32.5 to 2.33.0. Added requests>=2.33.0 as a direct dependency constraint in pyproject.toml (transitive via pytest-playwright) and regenerated the lockfile.

```bash
grep 'requests' pyproject.toml
```

```output
    "requests>=2.33.0",  # transitive via pytest-playwright; pinned to track updates
```

```bash
grep -A3 '^name = "requests"' uv.lock | head -4
```

```output
name = "requests"
version = "2.33.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [
```

```bash
uv run pytest selftests/ -q --no-header 2>&1 | grep -E 'passed|failed'
```

```output
95 passed, 2 warnings in 0.76s
```

```bash
uv run ruff check src/ tests/ selftests/ examples/ && uv run ruff format --check src/ tests/ selftests/ examples/
```

```output
All checks passed!
89 files already formatted
```
