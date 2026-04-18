# fix(performance): update locust install instructions to use uv

*2026-04-18T00:52:52Z by Showboat 0.6.1*
<!-- showboat-id: cfe3f95c-d3fa-4eb0-8a45-66e2a1c9e8a9 -->

Fixed three error messages that incorrectly suggested 'pip install posit-vip[load]' when locust is not installed. Updated all occurrences in src/vip/load_engine.py and src/vip/load_users.py to suggest 'uv sync --extra load' instead, consistent with VIP's uv-first toolchain policy.

```bash
grep -n 'uv sync' src/vip/load_engine.py src/vip/load_users.py
```

```output
src/vip/load_engine.py:191:        msg = f"locust not installed; {n} users with tool='locust' requires: uv sync --extra load"
src/vip/load_engine.py:337:        msg = "locust not installed; user simulation requires: uv sync --extra load"
src/vip/load_users.py:16:    msg = "locust is required for user simulation: uv sync --extra load"
```

```bash
uv run pytest selftests/ 2>&1 | grep -oE "[0-9]+ passed"
```

```output
243 passed
```

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ && uv run ruff format --check src/ src/vip_tests/ selftests/ examples/ && echo 'Lint and format: OK'
```

```output
All checks passed!
99 files already formatted
Lint and format: OK
```
