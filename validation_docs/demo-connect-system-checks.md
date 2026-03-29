# feat: Add Connect system checks test (issue #74)

*2026-03-23T16:59:59Z by Showboat 0.6.1*
<!-- showboat-id: 955dfeed-3e66-44a6-85a8-61438d68007a -->

Implements posit-dev/vip#74: adds a Connect system checks BDD test that triggers the built-in diagnostics, downloads the artifact, and embeds it in the VIP Quarto report.

Changes:
- ConnectClient: list_server_checks(), run_server_check(), get_server_check_report()
- tests/connect/test_system_checks.feature: @connect BDD scenario
- tests/connect/test_system_checks.py: step defs; saves artifact to report/connect_system_checks.html
- report/index.qmd: new 'Connect System Checks' section embeds the artifact via srcdoc iframe
- .github/workflows/example-report.yml: adds test_system_checks.py to CI smoke run

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

The index.qmd 'Connect System Checks' section renders when report/connect_system_checks.html exists (saved by the test step). When no system checks were run, it shows a placeholder message. The CI example-report.yml now includes test_system_checks.py in the smoke run so the section is populated in every PR preview.
