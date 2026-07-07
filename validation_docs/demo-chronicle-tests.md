# Feature: Workbench Chronicle observability test

*2026-07-07T17:20:00Z by Showboat 0.6.1*
<!-- showboat-id: 73ad029e-10bd-413b-8aa4-62f9bdf242f4 -->

Adds an in-session Chronicle data-collection test for Workbench. Chronicle has no query API, so the test launches an RStudio session and, inside it, reads Chronicle's telemetry back to prove it is collecting.

**Reads raw chunk files, not chronicle.reports.** Live validation against a real Chronicle-enabled Workbench (2026.06.0) showed the `chronicle.reports` R package only reads Chronicle's *daily/curated* Parquet datasets, which are produced by a deferred refinement step (the daily rollup lags real time by well over a day). A freshly configured deployment therefore has no chronicle.reports-readable data within any practical test window. Chronicle does write raw `*.csv` chunk files under its storage path within seconds of scraping — the same signal Posit's own Chronicle e2e suite asserts on — so the probe reads those directly.

The scenario asserts the two paths Chronicle collects deterministically, each via a representative metric confirmed present on Workbench 2026.06.0:
- Runtime metrics (Prometheus scrape) -> `pwb_active_user_sessions`.
- User information (Workbench admin API) -> `pwb_users` (needs `workbench-api-admin-enabled=1`).

Session events over OTLP are intentionally out of scope: a session launched by the test has not ended, so its lifecycle events are not flushed at probe time, and the path is gated on the Monitoring license — Posit's own e2e does not assert OTLP data landing either. The scenario is gated by the top-level `[chronicle] enabled` flag (shared with the Connect Chronicle test); `[workbench]` adds only `chronicle_data_path`. It auto-skips unless `[chronicle] enabled = true`, so it stays inert in the daily Workbench CI (which does not configure Chronicle).

The probe expression is built by a pure helper (`chronicle_probe.raw_chunk_probe_expr`) so it is unit-testable without a browser:

```bash
uv run pytest selftests/test_workbench_chronicle.py -q 2>&1 | grep -E 'passed|failed' | sed 's/ in [0-9.]*s//'
```

```output
9 passed
```

Config-loading and probe selftests together:

```bash
uv run pytest selftests/test_workbench_chronicle.py selftests/test_config.py -k "chronicle or ChunkProbe or RawChunk" -q 2>&1 | grep -E 'passed|failed' | sed 's/ in [0-9.]*s//'
```

```output
13 passed
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

**Live run (fuzzbucket, Workbench 2026.06.0+242.pro13)** — not reproducible in CI. Deployed an ubuntu22 box, enabled Chronicle (`chronicle-enabled=1`, `metrics-enabled=1`, `workbench-api-admin-enabled=1`, plus `[LocalStorage] Access = all` in `chronicle-local.gcfg` so the session user can read the data), and ran `vip verify --config vip.toml -f test_chronicle_collects_data -- -v`. The scenario `PASSED` (`1 passed`): it logged in via Playwright, launched and joined an RStudio session, read the `pwb_active_user_sessions` and `pwb_users` chunk files in-session (each a CSV with a header plus data rows, readable by the session user), and cleaned up the session. Confirmed green on two consecutive runs.
