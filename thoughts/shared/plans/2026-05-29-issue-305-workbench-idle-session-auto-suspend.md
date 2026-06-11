# Plan for issue #305: workbench idle session auto-suspend behavior

## Context

VIP's `test_sessions.feature` validates explicit suspend/resume workflows but does not verify automatic idle timeout behavior. Posit Team deployments configure `session-timeout-minutes` and `session-timeout-suspend` in `rsession.conf` to automatically suspend sessions after a period of inactivity. A customer UAT plan requires verifying two related behaviors: (1) an idle session auto-suspends after the configured timeout, and (2) an active session running long computations is not incorrectly suspended while work is in progress. Both assertions protect against timeout misconfigurations that could either leave orphaned sessions running or silently kill user work.

## Runtime constraint — read this first

A realistic customer idle timeout (e.g. 120 minutes) makes these scenarios run 2+ hours. **These tests are only viable against deployments configured with a short idle timeout.** The implementation must guard against this by skipping when `idle_timeout_minutes` exceeds a ceiling of **15 minutes**:

```python
MAX_VIABLE_IDLE_TIMEOUT_MINUTES = 15  # configurable per-deployment if needed

@given("the configured idle timeout is known", target_fixture="idle_timeout_minutes")
def configured_idle_timeout_known(vip_config):
    timeout = vip_config.workbench.idle_timeout_minutes
    if timeout is None:
        pytest.skip(
            "idle_timeout_minutes is not set in vip.toml — "
            "set [workbench] idle_timeout_minutes to the deployment's "
            "session-timeout-minutes value to enable this scenario"
        )
    if timeout > MAX_VIABLE_IDLE_TIMEOUT_MINUTES:
        pytest.skip(
            f"idle_timeout_minutes={timeout} exceeds the test ceiling of "
            f"{MAX_VIABLE_IDLE_TIMEOUT_MINUTES} min — configure the deployment "
            "with a shorter timeout to run these scenarios"
        )
    return timeout
```

The `vip.toml.example` comment must make this explicit: `idle_timeout_minutes = 5  # must be ≤ 15 for the idle scenarios to run`. Remove any example value of 120 from all documentation.

## Architecture

This change adds a new test feature file `test_session_idle.feature` and corresponding step definitions in `test_session_idle.py` under `src/vip_tests/workbench/`. It extends the `WorkbenchConfig` dataclass in `src/vip/config.py` to include an `idle_timeout_minutes` field that VIP reads from `vip.toml`. The new scenarios reuse existing session lifecycle helpers from `conftest.py` (`unique_session_name`, `workbench_login`, `assert_homepage_loaded`) and page object selectors from `pages/`. The active-session scenario uses the in-session R execution primitive (`rstudio_eval`) from `src/vip_tests/workbench/exec.py`, which was merged as part of issue #301 (PR #349, commit 3b336eb).

## Components

**Config and data model:**
- `src/vip/config.py` — add `idle_timeout_minutes: int | None = None` field to `WorkbenchConfig` alongside `job_timeout` and `test_packages` (lines ~197–229 on main); update `from_dict` to include `idle_timeout_minutes=raw.get("idle_timeout_minutes")` and update `__repr__` to include the new field after `test_packages`

**Test scenarios:**
- `src/vip_tests/workbench/test_session_idle.feature` — two Gherkin scenarios tagged `@workbench @performance`:
  - "Idle session auto-suspends after the configured timeout"
  - "Active session is not suspended while work is running"
- `src/vip_tests/workbench/test_session_idle.py` — step definitions for idle timeout scenarios, reusing existing session start/cleanup helpers

**Selftests:**
- `selftests/test_config.py` — add test cases verifying `idle_timeout_minutes` is loaded from TOML, defaults to `None`, and appears correctly in `__repr__`

**Documentation:**
- `vip.toml.example` — add `idle_timeout_minutes = 5` to the `[workbench]` section with a comment explaining it is the deployment's configured value and must be ≤ 15 for the scenarios to run

## Marker choice

Both scenarios are tagged `@performance`, not `@slow`. The `performance` marker is already registered in `src/vip/plugin.py::pytest_configure` and documented as opt-in/excluded by default. Adding a `@slow` marker would require registering it in `plugin.py` to avoid `--strict-markers` failures and user-visible warnings; `@performance` is the correct already-registered marker for tests that run long and need explicit opt-in.

## Config wiring

`WorkbenchConfig` currently declares fields in this order: `api_key`, `session_profiles`, `session_count`, `job_timeout`, `test_packages`, `extensions`, `kubernetes`. Add `idle_timeout_minutes` alongside `job_timeout` and `test_packages`, not after `kubernetes`. Concretely:

```python
# Field declaration — add after test_packages:
idle_timeout_minutes: int | None = None

# In WorkbenchConfig.from_dict — add after test_packages= line:
idle_timeout_minutes=raw.get("idle_timeout_minutes"),

# In WorkbenchConfig.__repr__ — append after test_packages=:
f"idle_timeout_minutes={self.idle_timeout_minutes!r}, "
f"extensions={self.extensions!r}, kubernetes={self.kubernetes!r})"
```

The field is `int | None` with `None` as default. There is no Workbench API that exposes the server's live `session-timeout-minutes` value — the test reads the operator-declared value from `vip.toml`, which the admin sets to match the deployment's `rsession.conf`.

## Active-session scenario: periodic activity loop

The active-session scenario must keep the session alive by sending periodic interactive input events, not a single blocking `Sys.sleep` spanning the whole window. A console blocked inside a long `Sys.sleep` is R being **busy**, not a session registering user *activity* — Workbench's idle timeout is driven by interactive input events, and a single blocking sleep may itself look idle to the server. It also means one synchronous Playwright wait spanning the entire window, which is fragile.

Instead, use a **periodic activity loop**: send a short `rstudio_eval` call of a trivial expression (e.g. `invisible(NULL)`) every 1–2 minutes across the window, each call emitting a real console input event that resets the idle clock:

```python
import time

@when("a long-running computation keeps the session active")
def long_running_computation(page, idle_timeout_minutes):
    # Drive the session with periodic interactive inputs across the full window.
    # Each rstudio_eval types an expression into the console, emitting an input
    # event that resets Workbench's idle clock — faithful to "activity correctly
    # resets the idle clock" from the issue.
    #
    # We poll for idle_timeout_minutes + 1 min (60s grace) in POLL_INTERVAL_S
    # increments, using a trivial expression that completes nearly instantly.
    POLL_INTERVAL_S = 90  # send an activity event every 90 seconds
    end_time = time.monotonic() + (idle_timeout_minutes * 60) + 60
    while time.monotonic() < end_time:
        rstudio_eval(page, "invisible(NULL)", timeout=15_000)
        remaining = end_time - time.monotonic()
        if remaining > 0:
            time.sleep(min(POLL_INTERVAL_S, remaining))
```

This loop:
1. Sends a real console input event every 90 seconds, faithfully resetting the idle clock via interactive activity.
2. Keeps each individual `rstudio_eval` timeout short (15 s), so failures surface quickly rather than hanging for the full window.
3. Is easy to reason about and unit-test (mock `time.monotonic` and verify call count).

After the loop, the step checks that the session is still in Active state.

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

## Note on TERMINAL_SESSION_FAILURE_STATES

`TERMINAL_SESSION_FAILURE_STATES` in `src/vip_tests/workbench/conftest.py` (line 39) currently contains only `("Failed",)` — `"Suspended"` is not in this tuple. This means PR #320's fail-fast logic will not false-fail the idle scenario when the session reaches Suspended state (which is the intended outcome for the idle test). No change is needed here, but implementers should be aware: the idle scenario's assertion of Suspended state is safe precisely because `wait_for_session_status` does not treat Suspended as a failure state.

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

A live end-to-end verification requires a Workbench deployment with a short idle timeout (≤ 15 minutes, e.g. 5 minutes) configured in `rsession.conf` and `idle_timeout_minutes = 5` in `vip.toml`. The idle scenario should pass when the session auto-suspends within `idle_timeout_minutes * 60 + 60` seconds; the active scenario verifies the session is still Active after the periodic activity loop runs for the full timeout window.

## Open questions

- The issue proposes a grace window (timeout + 60s) to account for clock drift. Should this be a fixed 60-second buffer, a configurable field, or a percentage of the timeout? Defaulting to a fixed 60-second buffer is simplest and matches the issue's suggestion. This can be revisited if deployments with high clock drift are encountered.
- Should the `@performance` marker automatically deselect these tests unless `--performance` is passed as a CLI flag, or is manual `pytest -m "not performance"` filtering sufficient? The existing `performance` marker is documented as opt-in/excluded by default but deselection is done via standard pytest `-m` expressions rather than a VIP-specific flag — this is consistent with the rest of VIP's performance tests.
- The 15-minute ceiling on `idle_timeout_minutes` is chosen as a pragmatic test limit. If a deployment legitimately uses a shorter timeout (e.g. 2–5 minutes), the ceiling can be tightened further. If a future VIP release adds a `--slow` / `--long-running` opt-in mechanism, the ceiling could become a soft advisory rather than a hard skip.

## Out of scope

- Adding a `--performance` CLI flag to VIP for one-click opt-in to all performance tests (separate enhancement).
- Validating timeout enforcement across different Workbench versions or deployment modes — the tests assert against the configured value, not the server implementation.
- Modifying the suspend/resume test in `test_sessions.py` (that scenario is already green and covers a different behavior).
