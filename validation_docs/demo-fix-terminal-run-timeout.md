# Fix #439: terminal_run swallows real command errors as a generic timeout

*2026-07-08T18:58:25Z by Showboat 0.6.1*
<!-- showboat-id: fb704d87-e7c6-4e3b-97a0-aeffe22dcc0b -->

Root cause: terminal_run's shell wrapper only wrote the done-marker via `&&`, so a fast-failing command (non-zero exit) never wrote the marker at all. The polling loop then waited out the full timeout and raised a generic 'timed out' error, discarding the real output sitting in the temp file the whole time.

The fix writes the marker unconditionally via `;` with the exit code appended (`marker:$?`), and a new pure helper `_parse_done_marker` parses it. `terminal_run` now raises `ExecError` immediately with the real captured output when the exit code is non-zero, instead of waiting out the full configured timeout.

## Before: the old `&&` marker is silently dropped on failure

This reproduces the exact shell wrapper that used to run inside the IDE terminal.

```bash
tmpfile=$(mktemp); cmd="false"; done_marker="VIP_DONE_old"; sh -c "${cmd} > ${tmpfile} 2>&1 && echo \"${done_marker}\" >> ${tmpfile}"; echo "--- tmpfile contents after a failing command ---"; cat "${tmpfile}"; echo "--- (marker present? )"; grep -q "${done_marker}" "${tmpfile}" && echo yes || echo "no -- polling loop would spin until timeout"
```

```output
--- tmpfile contents after a failing command ---
--- (marker present? )
no -- polling loop would spin until timeout
```

## After: the new `;` marker is always written, with the exit code

This reproduces the new shell wrapper used by the fixed `terminal_run`.

```bash
tmpfile=$(mktemp); cmd="ls /this/path/does/not/exist"; done_marker="VIP_DONE_new"; sh -c "${cmd} > ${tmpfile} 2>&1; echo \"${done_marker}:\$?\" >> ${tmpfile}"; echo "--- tmpfile contents after a failing command ---"; cat "${tmpfile}"; echo "--- (marker present? )"; grep -q "${done_marker}" "${tmpfile}" && echo "yes -- terminal_run parses this and raises ExecError immediately with the real output" || echo no
```

```output
--- tmpfile contents after a failing command ---
ls: cannot access '/this/path/does/not/exist': No such file or directory
VIP_DONE_new:2
--- (marker present? )
yes -- terminal_run parses this and raises ExecError immediately with the real output
```

## New unit tests covering the fix

`_parse_done_marker` is a pure, Playwright-free helper (matching this module's existing pattern) that parses the marker+exit-code line. `terminal_run` itself is also covered end-to-end with a mocked Playwright `page`, confirming: the marker is written unconditionally, success still returns output, a non-zero exit raises `ExecError` immediately (single poll, not a full timeout loop), and a genuinely hung command still times out.

```bash
uv run pytest selftests/test_workbench_exec.py -k "TestParseDoneMarker or TestTerminalRun" -v -n0 2>&1 | grep -E "PASSED|FAILED|ERROR|passed|failed" | sed -E "s/ in [0-9.]+s//"
```

```output
selftests/test_workbench_exec.py::TestParseDoneMarker::test_returns_none_when_marker_absent PASSED [ 10%]
selftests/test_workbench_exec.py::TestParseDoneMarker::test_parses_success_exit_code PASSED [ 20%]
selftests/test_workbench_exec.py::TestParseDoneMarker::test_parses_nonzero_exit_code PASSED [ 30%]
selftests/test_workbench_exec.py::TestParseDoneMarker::test_marker_line_removed_from_output PASSED [ 40%]
selftests/test_workbench_exec.py::TestParseDoneMarker::test_empty_output_between_marker PASSED [ 50%]
selftests/test_workbench_exec.py::TestParseDoneMarker::test_does_not_match_different_marker PASSED [ 60%]
selftests/test_workbench_exec.py::TestTerminalRun::test_writes_done_marker_unconditionally PASSED [ 70%]
selftests/test_workbench_exec.py::TestTerminalRun::test_returns_output_on_success PASSED [ 80%]
selftests/test_workbench_exec.py::TestTerminalRun::test_raises_exec_error_immediately_on_nonzero_exit PASSED [ 90%]
selftests/test_workbench_exec.py::TestTerminalRun::test_still_times_out_when_marker_never_appears PASSED [100%]
====================== 10 passed, 48 deselected =======================
```

## Full selftest suite still passes

```bash
uv run pytest selftests/ --ignore=selftests/test_load_engine.py -q 2>&1 | grep -E "passed|failed" | sed -E "s/ in [0-9.]+s//"
```

```output
870 passed, 26 warnings
```

## Lint and format checks pass

```bash
env -u VIRTUAL_ENV just check 2>&1
```

```output
uv run ruff check src/ selftests/ examples/ docker/
All checks passed!
uv run ruff format --check src/ selftests/ examples/ docker/
149 files already formatted
```
