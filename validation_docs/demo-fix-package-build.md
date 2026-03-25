# fix: include tests/ directory in the package wheel

*2026-03-25T19:02:37Z by Showboat 0.6.1*
<!-- showboat-id: 3b481eb5-b8b3-428c-ac91-1bcba3228e2b -->

The pyproject.toml only listed src/vip in the hatch wheel packages, so the tests/ directory was missing from the built wheel. Added tests to the packages list so all BDD test files are included when the package is installed.

```bash
uv build --wheel 2>&1 | tail -3
```

```output
Building wheel...
Successfully built dist/posit_vip-0.12.1-py3-none-any.whl
```

```bash
python -m zipfile -l dist/posit_vip-0.12.1-py3-none-any.whl | grep '^tests' | wc -l
```

```output
89
```

```bash
uv run pytest selftests/ 2>&1 | grep -E "passed|failed|error" | grep -oE "[0-9]+ passed"
```

```output
95 passed
```
