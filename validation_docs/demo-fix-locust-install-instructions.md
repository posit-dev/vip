# fix(performance): update locust install instructions to use uv

*2026-04-18T01:00:18Z by Showboat 0.6.1*
<!-- showboat-id: 3ca4640c-58db-4a03-abe0-ad5bb43e6c75 -->

Fixed three error messages that incorrectly suggested 'pip install posit-vip[load]' when locust is not installed. Updated all occurrences in src/vip/load_engine.py and src/vip/load_users.py to suggest both install paths: uv pip install for PyPI users and uv sync --extra load for source checkout developers.

```bash
grep -n 'posit-vip\[load\]' src/vip/load_engine.py src/vip/load_users.py
```

```output
src/vip/load_engine.py:193:            '(`uv pip install "posit-vip[load]"` for an installed package, '
src/vip/load_engine.py:343:            '(`uv pip install "posit-vip[load]"` for an installed package, '
src/vip/load_users.py:18:        '(`uv pip install "posit-vip[load]"` for an installed package, '
```

```bash
uv run pytest selftests/ 2>&1 | grep -oE '[0-9]+ passed'
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
