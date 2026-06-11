# Implement: #307 — Workbench-to-Connect publishing tests

## What was implemented

Added cross-product BDD test coverage for publishing Python Shiny
applications from Workbench sessions to Connect via `rsconnect deploy`.

### Changes

- `src/vip_tests/conftest.py` — promoted three Connect content-cleanup
  fixtures (`_connect_created_guids`, `_connect_content_cleanup`,
  `_connect_end_of_run_sweep`) from the Connect conftest to the root
  conftest so Workbench tests can register and auto-clean content too
- `src/vip_tests/connect/conftest.py` — removed those three fixtures;
  retained `_make_tar_gz` (imported directly by several test files)
- `src/vip_tests/workbench/conftest.py` — added `_PYTHON_SHINY_APP`
  constant and `python_shiny_bundle_path` fixture (session-scoped;
  writes a minimal `app.py` + `requirements.txt` to a tmp directory at
  test run time)
- `src/vip_tests/workbench/test_publish_to_connect.feature` — two new
  `@workbench @connect` scenarios: *User deploys a Python Shiny app via
  terminal* (active) and *User deploys via Posit Publisher extension UI*
  (stubbed with `pytest.skip` pending Publisher extension support)
- `src/vip_tests/workbench/test_publish_to_connect.py` — step
  definitions for both scenarios; terminal-deploy scenario drives VS Code
  via Playwright, runs `rsconnect deploy shiny …` in the terminal,
  discovers the content GUID from the Connect API, and verifies the app
  is reachable
- `selftests/test_publish_to_connect_fixtures.py` — AST-based selftests
  that confirm the fixture promotion and bundle fixture are correct (no
  live products required)

### Expected selftest results

```
selftests/test_publish_to_connect_fixtures.py::test_cleanup_fixtures_in_root_conftest PASSED
selftests/test_publish_to_connect_fixtures.py::test_cleanup_fixtures_not_in_connect_conftest PASSED
selftests/test_publish_to_connect_fixtures.py::test_make_tar_gz_preserved_in_connect_conftest PASSED
selftests/test_publish_to_connect_fixtures.py::test_python_shiny_bundle_path_in_workbench_conftest PASSED
selftests/test_publish_to_connect_fixtures.py::test_bundle_fixture_creates_app_and_requirements PASSED
selftests/test_publish_to_connect_fixtures.py::test_app_py_is_valid_python PASSED
```

### Lint

```
ruff check src/ selftests/ src/vip_tests/ examples/ — no issues
ruff format --check src/ selftests/ src/vip_tests/ examples/ — no issues
```
