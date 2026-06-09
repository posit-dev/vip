# Plan for issue #305: workbench idle session auto-suspend behavior

## Context

VIP's `test_sessions.feature` validates explicit suspend/resume workflows but does not verify automatic idle timeout behavior. Posit Team deployments configure `session-timeout-minutes` and `session-timeout-suspend` in `rsession.conf` to automatically suspend sessions after a period of inactivity. A customer UAT plan requires verifying two related behaviors: (1) an idle session auto-suspends after the configured timeout, and (2) an active session running long computations is not incorrectly suspended while work is in progress. Both assertions protect against timeout misconfigurations that could either leave orphaned sessions running or silently kill user work.

## Architecture

This change adds a new test feature file `test_session_idle.feature` and corresponding step definitions in `test_session_idle.py` under `src/vip_tests/workbench/`. It extends the `WorkbenchConfig` dataclass in `src/vip/config.py` to include an `idle_timeout_minutes` field that VIP reads from `vip.toml`. The new scenarios reuse existing session lifecycle helpers from `conftest.py` (`unique_session_name`, `workbench_login`, `assert_homepage_loaded`) and page object selectors from `pages/`. The active-session scenario uses the in-session R execution primitive (`rstudio_eval`) from `src/vip_tests/workbench/exec.py`, which was merged as part of issue #301 (PR #349, commit 3b336eb).

## Components

**Config and data model:**
- `src/vip/config.py` — add `idle_timeout_minutes: int | None = None` field to `WorkbenchConfig`; update `from_dict` to include `idle_timeout_minutes=raw.get("idle_timeout_minutes")` and update `__repr__` to include the new field

**Test scenarios:**
- `src/vip_tests/workbench/test_session_idle.feature` — two Gherkin scenarios tagged `@workbench @performance`:
  - "Idle session auto-suspends after the configured timeout"
  - "Active session is not suspended while work is running"
- `src/vip_tests/workbench/test_session_idle.py` — step definitions for idle timeout scenarios, reusing existing session start/cleanup helpers

**Selftests:**
- `selftests/test_config.py` — add test cases verifying `idle_timeout_minutes` is loaded from TOML, defaults to `None`, and appears correctly in `__repr__`

**Documentation:**
- `vip.toml.example` — add `idle_timeout_minutes = 120` to the `[workbench]` section with a comment explaining it is the deployment's configured value, not an enforcement setting

## Marker choice

Both scenarios are tagged `@performance`, not `@slow`. The `performance` marker is already registered in `src/vip/plugin.py::pytest_configure` and documented as opt-in/excluded by default. Adding a `@slow` marker would require registering it in `plugin.py` to avoid `--strict-markers` failures and user-visible warnings; `@performance` is the correct already-registered marker for tests that run long and need explicit opt-in.

## Config wiring

`WorkbenchConfig.from_dict` names every field explicitly (no `**kwargs` forwarding). Add the new field in both `from_dict` and `__repr__`:

```python
# In WorkbenchConfig.from_dict:
idle_timeout_minutes=raw.get("idle_timeout_minutes"),

# In WorkbenchConfig.__repr__ (append after kubernetes):
f"idle_timeout_minutes={self.idle_timeout_minutes!r})"
```

The field is an `int | None` with `None` as default. There is no Workbench API that exposes the server's live `session-timeout-minutes` value — the test reads the operator-declared value from `vip.toml`, which the admin sets to match the deployment's `rsession.conf`.

## Step for "configured idle timeout is known"

This step reads `vip_config.workbench.idle_timeout_minutes` (set via `vip.toml`) and calls `pytest.skip` when the value is `None`, so the scenario is silently omitted from deployments that have not declared a timeout. Example:

```python
@given("the configured idle timeout is known", target_fixture="idle_timeout_minutes")
def configured_idle_timeout_known(vip_config):
    timeout = vip_config.workbench.idle_timeout_minutes
    if timeout is None:
        pytest.skip(
            "idle_timeout_minutes is not set in vip.toml — "
            "set [workbench] idle_timeout_minutes to the deployment's "
            "session-timeout-minutes value to enable this scenario"
        )
    return timeout
```

## Active-session scenario: unblocked by #349

PR #349 (commit 3b336eb) merged `src/vip_tests/workbench/exec.py`, which provides `rstudio_eval(page, expr, timeout)` — a marker-bracketed R console primitive that types an R expression into the active RStudio session and returns captured output. This is the execution primitive the original plan deferred pending issue #301.

The active-session scenario uses `rstudio_eval` to keep the session alive by running a computation that lasts longer than the idle timeout, then asserts the session is still Active. Example step sketch:

```python
from vip_tests.workbench.exec import rstudio_eval

@when("a long-running computation keeps the session active")
def long_running_computation(page, idle_timeout_minutes):
    # Run a Sys.sleep that spans the full idle timeout window plus a 60-second buffer.
    # rstudio_eval types this into the RStudio console and waits for output.
    sleep_seconds = idle_timeout_minutes * 60 + 60
    rstudio_eval(page, f"Sys.sleep({sleep_seconds}); 'done'", timeout=(sleep_seconds + 30) * 1000)
```

The scenario does NOT use `pytest.skip` as a permanent stub — it is fully implementable now that `rstudio_eval` is available.

## Helper import paths

`assert_homepage_loaded`, `workbench_login`, `unique_session_name`, `wait_for_session_active`, and the timeout constants live in `src/vip_tests/workbench/conftest.py`. Import them the same way `test_sessions.py` does:

```python
from vip_tests.workbench.conftest import (
    TIMEOUT_CLEANUP,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_SESSION_START,
    assert_homepage_loaded,
    unique_session_name,
    wait_for_session_active,
    workbench_login,
)
```

Do **not** import these from `src/vip_tests/conftest.py` (the root conftest) — they are not defined there.

The `rstudio_eval` primitive is imported from `src/vip_tests/workbench/exec.py`:

```python
from vip_tests.workbench.exec import rstudio_eval
```

## Verification

1. Add the selftest cases and verify they pass:
   ```bash
   uv run pytest selftests/test_config.py::TestWorkbenchConfig::test_idle_timeout_default \
       selftests/test_config.py::TestWorkbenchConfig::test_idle_timeout_from_dict \
       selftests/test_config.py::TestWorkbenchConfig::test_repr_includes_idle_timeout -v
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
   Expected: two scenarios collected, both tagged `@workbench @performance`.

A live end-to-end verification requires a Workbench deployment with a known short idle timeout (e.g. 5 minutes) configured in `rsession.conf` and `idle_timeout_minutes = 5` in `vip.toml`. The idle scenario should pass when the session auto-suspends within `idle_timeout_minutes * 60 + 60` seconds; the active scenario verifies the session is still Active after `rstudio_eval` runs a computation for the full timeout window.

## Open questions

- The issue proposes a grace window (timeout + 60s) to account for clock drift. Should this be a fixed 60-second buffer, a configurable field, or a percentage of the timeout? Defaulting to a fixed 60-second buffer is simplest and matches the issue's suggestion. This can be revisited if deployments with high clock drift are encountered.
- Should the `@performance` marker automatically deselect these tests unless `--performance` is passed as a CLI flag, or is manual `pytest -m "not performance"` filtering sufficient? The existing `performance` marker is documented as opt-in/excluded by default but deselection is done via standard pytest `-m` expressions rather than a VIP-specific flag — this is consistent with the rest of VIP's performance tests.

## Out of scope

- Adding a `--performance` CLI flag to VIP for one-click opt-in to all performance tests (separate enhancement).
- Validating timeout enforcement across different Workbench versions or deployment modes — the tests assert against the configured value, not the server implementation.
- Modifying the suspend/resume test in `test_sessions.py` (that scenario is already green and covers a different behavior).
