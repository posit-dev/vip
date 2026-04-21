# fix(security): catch ConnectError with helpful skip messages

*2026-04-18T00:46:06Z by Showboat 0.6.1*
<!-- showboat-id: 15e86f26-b8d4-444e-aba0-c2307c1d5642 -->

Fixed issue #183: tests that make direct HTTP requests now catch httpx.ConnectError and call pytest.skip() with a clear message explaining the connectivity issue, rather than letting the raw httpcore.ConnectError propagate as an 'unexpected error'.

```bash
uv run pytest selftests/ -q 2>&1 | grep -E "passed|failed|error" | sed 's/ in [0-9.]*s//'
```

```output
243 passed, 4 warnings
```

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ && uv run ruff format --check src/ src/vip_tests/ selftests/ examples/ && echo 'All checks passed'
```

```output
All checks passed!
99 files already formatted
All checks passed
```
