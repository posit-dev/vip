# Implement: #301 — add in-session execution primitives for Workbench

## What was implemented

Added marker-bracketed in-session execution primitives for Workbench IDE tests,
plus a `test_packages` config field for package-install scenarios.

### Changes

- `src/vip_tests/workbench/exec.py` *(new)* — execution primitives module with:
  - `rstudio_eval`, `positron_eval_r`, `positron_eval_python` — R/Python console eval
  - `jupyterlab_eval` — notebook cell eval (Python or R kernel)
  - `vscode_eval` — VS Code Python/R REPL output panel eval
  - `terminal_run` — terminal redirect + DOM-rendered file readback (no xterm scraping)
  - `file_exists`, `read_file` — filesystem readback via console expressions
  - Pure helpers: `_wrap_r_expr`, `_wrap_python_expr`, `_extract_between_markers`,
    `_strip_r_index`, `_make_sentinels` — all fully unit-tested without Playwright

- `src/vip_tests/workbench/pages/positron_session.py` — added `CONSOLE_INPUT` selector

- `src/vip_tests/workbench/pages/vscode_session.py` — added `REPL_INPUT` and
  `REPL_OUTPUT` selectors for the VS Code Python/R Interactive Window

- `src/vip_tests/workbench/test_ide_launch.py` — refactored
  `rstudio_executes_r_code` step to delegate to `exec.rstudio_eval`,
  replacing the direct Playwright console interaction with the shared primitive

- `src/vip/config.py` — added optional `test_packages: list[str]` field to
  `WorkbenchConfig` (e.g. `["sf", "DBI", "Matrix"]`) for package-install scenarios

- `selftests/test_workbench_exec.py` *(new)* — 30 selftests covering:
  - `_make_sentinels`: format, uniqueness, shared UUID
  - `_wrap_r_expr`: marker presence, single-line output, expression inlining
  - `_wrap_python_expr`: marker presence, multi-line structure
  - `_extract_between_markers`: basic extraction, error paths, round-trip scenarios
  - `_strip_r_index`: prefix stripping, multi-line, edge cases

- `selftests/test_config.py` — four new tests for `WorkbenchConfig.test_packages`

### New config option

```toml
[workbench]
test_packages = ["sf", "DBI", "Matrix"]  # packages for install-verification scenarios
```

### Selftest results

```
selftests/test_workbench_exec.py::TestMakeSentinels::test_returns_two_strings PASSED
selftests/test_workbench_exec.py::TestMakeSentinels::test_start_has_vip_start_prefix PASSED
selftests/test_workbench_exec.py::TestMakeSentinels::test_end_has_vip_end_prefix PASSED
selftests/test_workbench_exec.py::TestMakeSentinels::test_unique_per_call PASSED
selftests/test_workbench_exec.py::TestMakeSentinels::test_hex_uid_in_sentinel PASSED
selftests/test_workbench_exec.py::TestWrapRExpr::test_full_marker_not_contiguous_in_source PASSED
selftests/test_workbench_exec.py::TestWrapRExpr::test_marker_halves_present PASSED
selftests/test_workbench_exec.py::TestWrapRExpr::test_contains_expression PASSED
selftests/test_workbench_exec.py::TestWrapRExpr::test_single_line_output PASSED
selftests/test_workbench_exec.py::TestWrapRExpr::test_markers_wrap_expression PASSED
selftests/test_workbench_exec.py::TestWrapRExpr::test_double_quotes_in_expr_inline PASSED
selftests/test_workbench_exec.py::TestWrapPythonExpr::test_full_marker_not_contiguous_in_source PASSED
selftests/test_workbench_exec.py::TestWrapPythonExpr::test_marker_halves_present PASSED
selftests/test_workbench_exec.py::TestWrapPythonExpr::test_contains_expression PASSED
selftests/test_workbench_exec.py::TestWrapPythonExpr::test_multiline_block PASSED
selftests/test_workbench_exec.py::TestWrapPythonExpr::test_start_print_is_first_line PASSED
selftests/test_workbench_exec.py::TestWrapPythonExpr::test_end_print_is_last_line PASSED
selftests/test_workbench_exec.py::TestExtractBetweenMarkers::test_basic_extraction PASSED
selftests/test_workbench_exec.py::TestExtractBetweenMarkers::test_strips_surrounding_whitespace PASSED
selftests/test_workbench_exec.py::TestExtractBetweenMarkers::test_empty_content_between_markers PASSED
selftests/test_workbench_exec.py::TestExtractBetweenMarkers::test_multi_line_content PASSED
selftests/test_workbench_exec.py::TestExtractBetweenMarkers::test_raises_on_missing_start_marker PASSED
selftests/test_workbench_exec.py::TestExtractBetweenMarkers::test_raises_on_missing_end_marker PASSED
selftests/test_workbench_exec.py::TestExtractBetweenMarkers::test_uses_first_start_marker PASSED
selftests/test_workbench_exec.py::TestExtractBetweenMarkers::test_full_round_trip_r PASSED
selftests/test_workbench_exec.py::TestExtractBetweenMarkers::test_full_round_trip_python PASSED
selftests/test_workbench_exec.py::TestStripRIndex::test_strips_single_index PASSED
selftests/test_workbench_exec.py::TestStripRIndex::test_strips_multi_digit_index PASSED
selftests/test_workbench_exec.py::TestStripRIndex::test_strips_multiple_lines PASSED
selftests/test_workbench_exec.py::TestStripRIndex::test_preserves_lines_without_index PASSED
selftests/test_workbench_exec.py::TestStripRIndex::test_empty_string PASSED
selftests/test_workbench_exec.py::TestStripRIndex::test_no_indices_returns_unchanged PASSED
selftests/test_workbench_exec.py::TestStripRIndex::test_quoted_string_result PASSED
selftests/test_workbench_exec.py::TestStripRIndex::test_strips_whitespace_after_index PASSED
selftests/test_config.py::TestWorkbenchConfig::test_test_packages_default_empty PASSED
selftests/test_config.py::TestWorkbenchConfig::test_test_packages_from_dict PASSED
selftests/test_config.py::TestWorkbenchConfig::test_test_packages_default_from_dict PASSED
selftests/test_config.py::TestWorkbenchConfig::test_test_packages_string_normalized_to_list PASSED
selftests/test_config.py::TestWorkbenchConfig::test_test_packages_invalid_type_raises PASSED
```

### Lint

```
ruff check src/ selftests/ src/vip_tests/ examples/ — no issues
ruff format --check src/ selftests/ src/vip_tests/ examples/ — no issues
```
