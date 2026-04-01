# feat(performance): add concurrent user load tests for each product

*2026-03-26T01:45:59Z by Showboat 0.6.1*
<!-- showboat-id: 254e5410-20b4-4683-b23b-3d836a1ac03c -->

Implemented load tests (issue #117) that simulate concurrent authenticated users against each Posit Team product. Unlike the existing health-check concurrency tests, these tests use product credentials to make real API calls: Connect lists content, Workbench queries server settings, Package Manager lists repos. Scenarios run at 10, 20, 50, and 100 concurrent users.

```bash
uv run pytest src/vip_tests/performance/test_load.py --collect-only -q 2>&1 | grep -v UserWarning | grep -v 'Config file' | grep -v 'vip_cfg'
```

```output
src/vip_tests/performance/test_load.py::test_connect_handles_users_concurrent_authenticated_users[10]
src/vip_tests/performance/test_load.py::test_connect_handles_users_concurrent_authenticated_users[20]
src/vip_tests/performance/test_load.py::test_connect_handles_users_concurrent_authenticated_users[50]
src/vip_tests/performance/test_load.py::test_connect_handles_users_concurrent_authenticated_users[100]
src/vip_tests/performance/test_load.py::test_workbench_handles_users_concurrent_users[10]
src/vip_tests/performance/test_load.py::test_workbench_handles_users_concurrent_users[20]
src/vip_tests/performance/test_load.py::test_workbench_handles_users_concurrent_users[50]
src/vip_tests/performance/test_load.py::test_workbench_handles_users_concurrent_users[100]
src/vip_tests/performance/test_load.py::test_package_manager_handles_users_concurrent_users[10]
src/vip_tests/performance/test_load.py::test_package_manager_handles_users_concurrent_users[20]
src/vip_tests/performance/test_load.py::test_package_manager_handles_users_concurrent_users[50]
src/vip_tests/performance/test_load.py::test_package_manager_handles_users_concurrent_users[100]

12 tests collected in 0.02s
```

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -oE '^[0-9]+ passed'
```

```output
95 passed
```
