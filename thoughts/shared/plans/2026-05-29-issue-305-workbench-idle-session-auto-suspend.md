# Plan for issue #305: workbench idle session auto-suspend behavior

## Context

VIP's `test_sessions.feature` validates explicit suspend/resume workflows but does not verify automatic idle timeout behavior. Posit Team deployments configure `session-timeout-minutes` and `session-timeout-suspend` in `rsession.conf` to automatically suspend sessions after a period of inactivity. A customer UAT plan requires verifying two related behaviors: (1) an idle session auto-suspends after the configured timeout, and (2) an active session running long computations is not incorrectly suspended while work is in progress. Both assertions protect against timeout misconfigurations that could either leave orphaned sessions running or silently kill user work.

## Architecture

This change adds a new test feature file `test_session_idle.feature` and corresponding step definitions in `test_session_idle.py` under `src/vip_tests/workbench/`. It extends the `WorkbenchConfig` dataclass in `src/vip/config.py` to include an `idle_timeout_minutes` field that VIP reads from `vip.toml`. The new scenarios reuse existing session lifecycle helpers from `conftest.py` (`unique_session_name`, `workbench_login`, `assert_homepage_loaded`) and page object selectors from `pages/`. The active-session scenario will depend on an in-session code execution primitive (referenced as a separate issue in #305's notes) — for now that scenario can be stubbed with a `pytest.skip` pending that primitive.

## Components

**Config and data model:**
- `src/vip/config.py` — add `idle_timeout_minutes: int | None = None` field to `WorkbenchConfig`, update `from_dict` and `__repr__` methods

**Test scenarios:**
- `src/vip_tests/workbench/test_session_idle.feature` — two Gherkin scenarios: "Idle session auto-suspends after the configured timeout" and "Active session is not suspended while work is running", both tagged `@workbench @slow`
- `src/vip_tests/workbench/test_session_idle.py` — step definitions for idle timeout scenarios, reusing existing session start/cleanup helpers

**Selftests:**
- `selftests/test_config.py` — add a test case verifying `idle_timeout_minutes` is loaded from TOML and defaults to `None`

**Documentation:**
- `vip.toml.example` — add `idle_timeout_minutes = 120` to the `[workbench]` section with a comment explaining it is the deployment's configured value, not an enforcement setting

## Verification

1. Add the selftest case and verify it passes:
   ```bash
   uv run pytest selftests/test_config.py::test_workbench_config_idle_timeout -v
   ```
2. Run ruff checks:
   ```bash
   uv run ruff check src/ selftests/
   uv run ruff format --check src/ selftests/
   ```
3. Collect the new idle timeout scenarios without running them (no deployment available in dev):
   ```bash
   uv run pytest src/vip_tests/workbench/test_session_idle.py --collect-only
   ```
   Expected: two scenarios collected, both tagged `@workbench @slow`.

A live end-to-end verification requires a Workbench deployment with a known short idle timeout (e.g. 5 minutes) configured in `rsession.conf`. The idle scenario should pass when the timeout is correctly reflected in `vip.toml` and the session auto-suspends; the active scenario will initially skip pending the in-session execution primitive.

## Open questions

- **UNCONFIRMED**: The in-session code execution primitive is referenced as a "separate issue" in #305 but no issue number is provided. The active-session scenario cannot be fully implemented until that primitive is available. For now the step definition should skip with a message stating the dependency.
- The issue proposes a grace window (timeout + 60s) to account for clock drift. Should this be a fixed 60-second buffer, a configurable field, or a percentage of the timeout? Defaulting to a fixed 60-second buffer is simplest and matches the issue's suggestion.
- Should the `@slow` marker automatically skip these tests unless a CLI flag or config opt-in is present, or is manual `pytest -k` filtering sufficient? The issue states "skipped by default unless the deployment opts in" — this could be a new `run_slow_tests` boolean in `WorkbenchConfig` or a pytest marker deselection in `conftest.py`. Leaving this as manual filtering (`pytest -m "not slow"`) is the least invasive option.

## Out of scope

- Implementing the in-session code execution primitive (separate issue).
- Adding a UI or config flag for opting into `@slow` tests (can be done manually with `pytest -m "not slow"` or `pytest -m slow`).
- Validating timeout enforcement across different Workbench versions or deployment modes — the tests assert against the configured value, not the server implementation.
- Modifying the suspend/resume test in `test_sessions.py` (that scenario is already green and covers a different behavior).
