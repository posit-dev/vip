# Implement: #302 — workbench jobs coverage

## What was implemented

Added BDD test coverage for Workbench Background Jobs and Workbench Jobs
(Launcher jobs) in RStudio Pro sessions.

### Changes

- `src/vip/config.py` — added `job_timeout` field to `WorkbenchConfig`
  (default 120 s, configurable via `[workbench] job_timeout` in vip.toml)
- `src/vip_tests/workbench/test_jobs.feature` — two new `@workbench`
  scenarios: *Background Job runs and completes* and *Workbench Job runs
  and completes*
- `src/vip_tests/workbench/test_jobs.py` — Playwright step definitions for
  both scenarios, with graceful `pytest.skip` guards when the Jobs UI is
  unavailable
- `src/vip_tests/workbench/pages/rstudio_session.py` — job-related
  selectors for Background Jobs and Workbench Jobs panes
- `selftests/test_config.py` — three new tests covering `job_timeout`
  default, from-dict parsing, and explicit value round-trip

### New config option

```toml
[workbench]
job_timeout = 300  # seconds; increase for slow clusters (default: 120)
```

### Selftest results

```
selftests/test_config.py::TestWorkbenchConfig::test_job_timeout_default PASSED
selftests/test_config.py::TestWorkbenchConfig::test_job_timeout_from_dict PASSED
selftests/test_config.py::TestWorkbenchConfig::test_job_timeout_default_from_dict PASSED
```

### Lint

```
ruff check src/ selftests/ src/vip_tests/ examples/ — no issues
ruff format --check src/ selftests/ src/vip_tests/ examples/ — no issues
```
