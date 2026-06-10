# Plan for issue #288: improved timeout configuration

## Context

Issue #288 is an operational request: QA testers run VIP against Posit Team on
small VMs, where operations like **launching a Workbench session** or
**deploying content to Connect** take much longer than on production hardware.
Many of VIP's timeouts are bare literals that operators cannot tune, so they hit
flaky timeouts they have no lever for. The issue explicitly asks for *either*
(a) significantly longer defaults *or* (b) a way to scale timeouts up/down.

The cleanest answer to "scale every timeout up for a slow VM" is a single global
multiplier the operator sets per run. This plan adds one env var,
`VIP_TIMEOUT_SCALE`, applied at every real operation-timeout chokepoint —
including the two the issue names by name (Workbench session launch, Connect
deploy) and the SSO login path, which are the slowest operations on a small VM.

### Why a single env-var multiplier (and not a new config taxonomy)

An earlier draft of this plan proposed a 17-field `[timeouts]` config section, a
new `TimeoutConfig` dataclass module, and a three-level precedence bridge. That
was rejected for three reasons:

1. **It missed the slow paths it promised to cover.** It never touched
   `src/vip/idp.py` (the IdP login-form waits) and could not reach the
   Workbench Playwright constants in `src/vip_tests/workbench/conftest.py`
   (`TIMEOUT_SESSION_START = 90_000`, `TIMEOUT_IDE_LOAD = 60_000`) because step
   files import those constants at module-load time, before any pytest fixture
   exists. A fixture-based knob cannot reach an import-time constant.
2. **A plumbing hole.** It said literals would read
   `vip_config.timeouts.effective(...)`, but `BaseClient.__init__`,
   `src/vip/auth.py`, and `src/vip/idp.py` do not have `vip_config` in scope.
3. **Over-built for the ask.** The issue wants a lever, not a per-operation
   taxonomy that has to be kept in sync with every literal.

**The key insight:** the thing that blocked the fixture approach — needing a
value at module-import time — is trivially solved by an environment variable,
which *is* available at import time. A single `VIP_TIMEOUT_SCALE` read by a
dependency-free leaf helper can be applied uniformly in `conftest.py`,
`idp.py`, `auth.py`, the clients, and the job runner, with no `vip_config`
plumbing and no new config schema.

## Architecture

### The scale helper (one tiny leaf module)

Add `src/vip/timeouts.py` containing only:

```python
import os

def timeout_scale() -> float:
    """Global multiplier for operation timeouts, from VIP_TIMEOUT_SCALE.

    Returns 1.0 when unset or invalid. Read fresh on each call so it works
    both at module-import time (Playwright/IdP constants) and at call time
    (auth flows, clients). Values <= 0 are ignored (fall back to 1.0).
    """
    raw = os.environ.get("VIP_TIMEOUT_SCALE")
    if raw is None:
        return 1.0
    try:
        value = float(raw)
    except ValueError:
        return 1.0
    return value if value > 0 else 1.0

def scaled(value: float) -> float:
    """Multiply a timeout (seconds or milliseconds) by the global scale."""
    return value * timeout_scale()
```

This module imports **nothing from VIP**, so it is import-safe everywhere and
cannot create circular imports. It deliberately holds no dataclass and no
config coupling — it is a leaf, not a config layer. (This is the one new file;
it is ~15 lines, which is why it does not warrant living inside the larger
`config.py`: it must be importable from modules that `config.py` itself may
import.)

### Why env var, not a `vip.toml` field (resolved design decision)

`VIP_TIMEOUT_SCALE` is **env-var only**, by design:

- It must be readable at module-import time for the Playwright/IdP constants;
  `vip.toml` is not parsed that early.
- The use case is a per-run operator lever (`VIP_TIMEOUT_SCALE=3 vip verify …`
  on a slow QA VM), for which an env var is the natural ergonomics.

This removes the earlier draft's unresolved "env wins vs. file wins" question
entirely: there is no competing file value for `scale`. The existing
per-section absolute knobs (`[connect].deploy_timeout`, `[workbench].job_timeout`,
`[performance].page_load_timeout` / `download_timeout`) stay exactly as they are
for operators who want to set a specific fixed value; the scale multiplies on
top of whatever effective value (default or configured) is in play.

### Application points (the chokepoints)

`scaled(...)` is applied at every genuine operation timeout. Human-wait and
busy-loop-pacing values are deliberately excluded (see Out of scope).

## Components

**New file:**

- `src/vip/timeouts.py` — the `timeout_scale()` / `scaled()` helpers above.
- `selftests/test_timeouts.py` — see Verification for the cases.

**Modified files — production timeouts wired through `scaled()`:**

- `src/vip_tests/workbench/conftest.py` — the seven module-level constants
  (verified at lines 24-30) become scale-aware at import:
  `TIMEOUT_QUICK = int(5_000 * timeout_scale())`, and likewise for
  `TIMEOUT_DIALOG` (10_000), `TIMEOUT_PAGE_LOAD` (15_000),
  `TIMEOUT_CLEANUP` (30_000), `TIMEOUT_CODE_EXEC` (30_000),
  `TIMEOUT_IDE_LOAD` (60_000), `TIMEOUT_SESSION_START` (90_000). Because step
  files import these names directly (`test_sessions.py`, `test_ide_launch.py`,
  `test_packages.py`, `test_jobs.py`, `test_ide_extensions.py`,
  `test_data_sources.py`, `test_session_capacity.py`,
  `test_session_capacity_k8s.py` — 8 files), scaling the constants at definition
  time reaches all of them with **no call-site changes** — this is what fixes
  the "Workbench session launch" path the issue names.

- `src/vip/idp.py` — the IdP login-form waits become scale-aware at import:
  `_FORM_TIMEOUT = int(15_000 * timeout_scale())` (line 29) and
  `_MFA_DETECT_TIMEOUT = int(10_000 * timeout_scale())` (line 31). The
  `networkidle` wait (line 277, 10_000 ms) is wrapped with `scaled(...)` at the
  call site. `_MFA_TIMEOUT` (line 33, 300_000 ms / 5 min) is a **human** wait
  and is left unscaled (see Out of scope). The three `wait_for_timeout(500)`
  pacing sleeps (lines 239, 246, 299) are left unscaled.

- `src/vip/auth.py` — wrap the operation timeouts with `scaled(...)` at their
  call sites: the `page.click(..., timeout=3_000)` (line 704), the
  `wait_for_url(..., timeout=10_000)` (line 716), the
  `wait_for(timeout=15_000)` (line 740), the `page.click(..., timeout=2_000)`
  (line 868), the `wait_for_load_state("networkidle", timeout=5_000)`
  (line 881), the two `deadline = time.monotonic() + 300` loops (lines 396,
  750), the `+ 120` deadline (line 877), and the `timeout=10.0` httpx calls
  (lines 962, 1236, 1245, 1348). The three `wait_for_timeout(500)` pacing
  sleeps (lines 419, 768, 892) are **not** scaled — they are deliberate poll
  intervals in the interactive-login busy loop; scaling them only slows the
  loop on fast machines.

- `src/vip/clients/base.py` — `BaseClient.__init__` (line 44) currently defaults
  `timeout: float = 30.0`. Change the default sentinel to `None` and resolve
  `effective = scaled(30.0) if timeout is None else timeout`, so every client
  (`ConnectClient` connect.py:33, `WorkbenchClient` workbench.py:30,
  `PackageManagerClient` packagemanager.py:12 — all currently `= 30.0`,
  changed to `= None` pass-through) picks up the scale unless a caller passes an
  explicit value. An explicitly-passed timeout is honored as-is (callers who
  already chose a number opt out of scaling).

- `src/vip/clients/connect.py` — `wait_for_task(timeout=60.0)` (line 185) and
  `wait_for_system_check(timeout=120.0)` (line 398): same sentinel pattern —
  default to `None`, resolve to `scaled(60.0)` / `scaled(120.0)`.

- `src/vip/cli.py` — the two process-level timeouts that govern long
  operations on slow VMs: `DEFAULT_TEST_TIMEOUT_SECONDS = 3600` (line 29, the
  local-mode pytest subprocess budget) and the `--timeout` k8s job flag
  (default 900, line 1198). Apply `scaled(...)` to the *default* only, so an
  operator who passes `--timeout` explicitly is not double-scaled. Note the
  derived chain: `create_job(timeout_seconds = args.timeout - 60)` (cli.py:633,
  feeding job.py:56 → `activeDeadlineSeconds` job.py:109) and `stream_logs` /
  `wait_for_job` (job.py:249, 274, default 900) all flow from `args.timeout`, so
  scaling that single default propagates correctly to the Kubernetes deadline
  and the polling budget without touching `job.py` itself.

- `src/vip/verify/credentials.py` — the two `httpx.Client(timeout=30.0)`
  instances (lines 516, 592) bypass `BaseClient`; wrap each with
  `scaled(30.0)`.

**Modified files — hardcoded test literals that bypass config (corrected to scale):**

- `src/vip_tests/connect/test_packages.py` (line 93) and
  `src/vip_tests/connect/test_integration.py` (line 48) call
  `wait_for_task(timeout=300)` with a hardcoded value that ignores both
  `deploy_timeout` and the scale. Change them to call `wait_for_task()` without
  an explicit timeout so they inherit the (now scale-aware) default, or pass
  `scaled(300)` if 300 s specifically is required.

- `src/vip_tests/performance/test_login_load_times.py` (line 38) already
  multiplies `performance_config.page_load_timeout * 3`. Leave the `* 3`
  intent but note that `page_load_timeout` arrives unscaled from config; if
  uniform scaling is desired here, wrap with `scaled(...)`. (Low priority — this
  is a performance test, opt-in and excluded by default.)

**Documentation:**

- `vip.toml.example` — add a short comment near the existing timeout knobs
  pointing operators at `VIP_TIMEOUT_SCALE` for global dilation on slow VMs,
  with the worked example `VIP_TIMEOUT_SCALE=3 vip verify --connect-url …`.
- `docs/test-architecture.md` — a short "Tuning timeouts on slow hardware"
  subsection: the env var, what it scales, and what it deliberately does not
  (human MFA wait, UI pacing sleeps).
- `validation_docs/demo-bot-plan-issue-288.md` — showboat demo running the new
  selftests and `ruff check` (created post-implementation per the demo workflow).

## Verification

```bash
# 1. Lint / format.
uv run ruff check src/ src/vip_tests/ selftests/ examples/
uv run ruff format --check src/ src/vip_tests/ selftests/ examples/

# 2. New unit tests.
uv run pytest selftests/test_timeouts.py -v

# 3. No regressions in the existing suite.
uv run pytest selftests/ -v

# 4. Product-test collection still works (the conftest constant change is the
#    riskiest edit — confirm collection does not break).
uv run pytest src/vip_tests/ --collect-only -q

# 5. Smoke-test the multiplier end to end.
VIP_TIMEOUT_SCALE=2 uv run python -c "from vip.timeouts import scaled; assert scaled(30.0) == 60.0; print('client default 30 ->', scaled(30.0))"
VIP_TIMEOUT_SCALE=2 uv run python -c "import vip_tests.workbench.conftest as c; assert c.TIMEOUT_SESSION_START == 180_000; print('session start ->', c.TIMEOUT_SESSION_START)"
```

`selftests/test_timeouts.py` cases:

1. `timeout_scale()` returns `1.0` when `VIP_TIMEOUT_SCALE` is unset.
2. `timeout_scale()` reads the env var (`monkeypatch.setenv("VIP_TIMEOUT_SCALE", "2.5")` → `2.5`).
3. Invalid (`"abc"`) and non-positive (`"0"`, `"-1"`) values fall back to `1.0`.
4. `scaled(30.0)` returns `30.0` at default and `60.0` at scale 2.
5. The Workbench conftest constants reflect the scale after a reload:
   `monkeypatch.setenv("VIP_TIMEOUT_SCALE", "2")`, `importlib.reload(conftest)`,
   assert `TIMEOUT_SESSION_START == 180_000`; reload again unset to restore.
6. A client constructed with no explicit timeout uses `scaled(30.0)`; a client
   constructed with `timeout=5.0` keeps `5.0` (explicit opts out of scaling).

Success looks like: the new selftests pass, the existing selftests still pass,
product-test collection still works, and both smoke-test asserts hold.

## Out of scope (deliberately not scaled)

- **Human-wait timeouts.** `idp.py:_MFA_TIMEOUT` (5-minute MFA prompt window) is
  a wait for a person, not a server; scaling it is meaningless.
- **Busy-loop pacing sleeps.** All `page.wait_for_timeout(500)` /
  `wait_for_timeout(1000)` calls (auth.py:419,768,892; idp.py:239,246,299;
  test_session_capacity.py:108; test_session_capacity_k8s.py:67;
  test_jobs.py:292) are poll intervals, not operation deadlines. Scaling them
  slows the loop without preventing any timeout.
- **A per-operation config taxonomy.** Explicitly rejected — the existing
  per-section knobs plus a global multiplier cover the issue's need. If a future
  need for per-operation absolute control appears, it can be added then.
- **Retries / backoff** — the issue is about durations, not retry policy.
- **CI workflow timeouts** under `.github/workflows/` — GitHub Actions-level,
  outside this code and forbidden by the agent denylist.

## Open questions

None blocking. The env-vs-file precedence and MFA-exclusion questions from the
earlier draft are resolved above by making `scale` env-only and excluding human
waits explicitly.
