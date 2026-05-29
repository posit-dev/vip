# Fix: #283 — treat empty manifest as missing

## Test the fix

```bash
uv run pytest selftests/install/test_manifest.py::test_load_empty_file_returns_none -v 2>&1 | sed 's/ in [0-9.]*s//'
```

```
============================= test session starts ==============================
platform linux -- Python 3.12.8, pytest-8.3.4, pluggy-1.5.0 -- /home/runner/work/vip/vip/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/runner/work/vip/vip
configfile: pyproject.toml
plugins: playwright-0.6.2, timeout-2.3.1, bdd-8.0.0
collected 1 item

selftests/install/test_manifest.py::test_load_empty_file_returns_none PASSED

============================== 1 passed, 1 warning
```

## Verify lint passes

```bash
uv run ruff check src/ selftests/
```

```
All checks passed!
```
