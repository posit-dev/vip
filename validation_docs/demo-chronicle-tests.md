# Feature: Workbench Chronicle observability test

*2026-07-07T15:05:35Z by Showboat 0.6.1*
<!-- showboat-id: 73ad029e-10bd-413b-8aa4-62f9bdf242f4 -->

Adds an in-session Chronicle data-collection test. Chronicle stores telemetry only as Parquet files on the Workbench server (no query API), so the test launches an RStudio session and, inside it, uses the chronicle.reports R package (posit-dev/chronicle-reports) to confirm Chronicle has written queryable data.

Chronicle collects through three independent paths; enabling chronicle_enabled asserts full functionality, so the scenario verifies all three via the raw metric each path produces:
- Runtime metrics (Prometheus scrape) -> pwb_sessions_launched_total (works on enable).
- User information (Workbench admin API) -> pwb_users (needs workbench-api-admin-enabled=1).
- Session events (OpenTelemetry logs) -> pwb_sessions (needs otel-* config + [Workbench] LogOTLPEndpoint + Monitoring license).

The path->metric->receiver mapping was verified against the chronicle source: pwb_users is emitted by the workbenchapi receiver, and pwb_sessions is built from OTLP log events (convertPWBSession(logs)). New [workbench] config: chronicle_enabled (gate, default false) and chronicle_data_path. The scenario auto-skips unless chronicle_enabled = true, so it stays inert in the daily Workbench CI (which does not configure Chronicle).

```bash
uv run pytest selftests/test_config.py -k chronicle -q 2>&1 | grep -E 'passed|failed' | sed 's/ in [0-9.]*s//'
```

```output
7 passed
```

```bash
uv run pytest src/vip_tests/workbench/test_chronicle.py --collect-only -q -p no:vip 2>&1 | grep -E 'test_|collected' | sed 's/ in [0-9.]*s//'
```

```output
src/vip_tests/workbench/test_chronicle.py::test_chronicle_collects_data[chromium]
1 test collected
```

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

The embedded R probe was validated against the R interpreter: it parses cleanly and returns the expected VIP_NO_PKG sentinel when chronicle.reports is absent; the VIP_DATA_OK / VIP_NO_DATA branches were exercised with stubbed data (missing dataset, 0 rows, and rows in daily/hourly).

**Live run requirements** (not executable in CI): a Workbench deployment with Chronicle fully configured (chronicle-enabled=1 + metrics-enabled=1; workbench-api-admin-enabled=1; otel-* log export + [Workbench] LogOTLPEndpoint + Monitoring license); chronicle.reports installed in the session R library; the session user able to read chronicle_data_path (set [LocalStorage] Access = all in chronicle-local.gcfg, or group membership); and chronicle_enabled = true in vip.toml. Then: 'vip verify --config vip.toml --categories workbench -- -k chronicle' runs the scenario end to end.
