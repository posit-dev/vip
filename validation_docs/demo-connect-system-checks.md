# Connect System Checks Test

*2026-04-06T16:12:06Z by Showboat 0.6.1*
<!-- showboat-id: c6e70bbb-606e-498d-ba58-2249302a2ab2 -->

Added a BDD test that triggers Connect system diagnostics via the /v1/server_checks API, verifies the report completes, and downloads the artifact. New ConnectClient methods: list_server_checks(), run_server_check(), get_server_check_report().

```bash
uv run ruff check src/ selftests/ examples/ && uv run ruff format --check src/ selftests/ examples/ > /dev/null && echo 'All checks passed'
```

```output
All checks passed!
All checks passed
```

Selftests: 110 passed. System checks test collected: 1 test (test_connect_system_checks).
