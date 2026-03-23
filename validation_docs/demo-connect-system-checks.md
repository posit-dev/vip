# feat: Add Connect system checks test (issue #74)

*2026-03-23T13:48:44Z by Showboat 0.6.1*
<!-- showboat-id: e842db8b-7754-4653-9d5b-3cfdb9c8a078 -->

Added a Connect system checks test that triggers the built-in Connect server diagnostics and downloads the resulting report artifact, implementing posit-dev/vip#74.

Changes:
- Added list_server_checks(), run_server_check(), and get_server_check_report(check_id) to ConnectClient
- Added tests/connect/test_system_checks.feature with @connect-tagged BDD scenario
- Added tests/connect/test_system_checks.py with step definitions

The test triggers a new system check run (POST /v1/server_checks), verifies the report contains an 'id' field, then downloads the artifact (GET /v1/server_checks/{id}/download).

```bash
uv run ruff check src/ tests/ selftests/ examples/ && uv run ruff format --check src/ tests/ selftests/ examples/ && echo 'Lint/format: OK'
```

```output
All checks passed!
90 files already formatted
Lint/format: OK
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -oE '^[0-9]+ passed, [0-9]+ warnings'
```

```output
95 passed, 2 warnings
```

```bash
uv run pytest tests/connect/test_system_checks.py --collect-only -q 2>&1 | grep -v 'UserWarning\|vip_cfg\|plugin.py' | grep -v 'in [0-9]'
```

```output
tests/connect/test_system_checks.py::test_connect_system_checks

```
