# feat(performance): add concurrent user load tests for each product

*2026-03-26T01:45:59Z by Showboat 0.6.1*
<!-- showboat-id: 254e5410-20b4-4683-b23b-3d836a1ac03c -->

Implemented load tests (issue #117) that simulate concurrent authenticated users against each Posit Team product. Unlike the existing health-check concurrency tests, these tests use product credentials to make real API calls: Connect lists content, Workbench queries server settings, Package Manager lists repos. A new 'load_users' config field (default: 10) controls the number of simulated concurrent users.

```bash
uv run pytest src/vip_tests/performance/test_load.py --collect-only -q 2>&1 | grep -v UserWarning | grep -v 'Config file' | grep -v 'vip_cfg'
```

```output
src/vip_tests/performance/test_load.py::test_connect_load
src/vip_tests/performance/test_load.py::test_workbench_load
src/vip_tests/performance/test_load.py::test_pm_load

3 tests collected in 0.01s
```

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ && uv run ruff format --check src/ src/vip_tests/ selftests/ examples/ && echo 'All lint checks passed'
```

```output
All checks passed!
All lint checks passed
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -oE '^[0-9]+ passed'
```

```output
95 passed
```
