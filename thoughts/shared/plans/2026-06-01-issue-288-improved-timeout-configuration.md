# Plan for issue #288: improved timeout configuration

## Context

VIP currently scatters timeout values across the codebase as either hardcoded
literals or per-section config knobs. When the suite runs against
Marketplaces / QA deployments on small VMs, operations like Workbench session
launch and Connect content deploy regularly exceed those defaults and the run
fails for environmental rather than functional reasons. The issue reporter
asked for either significantly larger defaults or more configuration levers
to scale timeouts up or down per deployment.

The goal of this change is to centralize timeouts in one config section,
expose every meaningful timeout as a named field, and add a single global
`scale` multiplier (plus a matching env var) so an operator running on a
slow VM can set `scale = 3.0` once and have every wait scaled uniformly
without editing source.

## Architecture

A new `TimeoutsConfig` dataclass is added to `src/vip/config.py` alongside
the existing `PerformanceConfig`. It owns all timeout values that production
code currently hardcodes or scatters across other config classes.

The dataclass exposes a single helper, `TimeoutsConfig.get(name)`, that
returns the configured value for the named timeout multiplied by the global
`scale` factor. Every call site is converted from a hardcoded literal to a
call against this helper.

For backwards compatibility, two existing knobs keep working:

- `ConnectConfig.deploy_timeout` — when set in `[connect]`, it overrides
  `timeouts.connect_deploy`. Otherwise the new field is used.
- `PerformanceConfig.page_load_timeout` — same pattern under `[performance]`.

The precedence rule, in order: explicit per-section override → `[timeouts]`
field → built-in default. The `scale` multiplier is always applied last.

The `VIP_TIMEOUT_SCALE` env var, when set, overrides `timeouts.scale` so CI
and one-off runs can scale timeouts without editing `vip.toml`.

## Components

**New files:**
- `selftests/test_timeouts_config.py` — covers defaults, per-field override,
  the `scale` multiplier, the `VIP_TIMEOUT_SCALE` env var, and the
  backwards-compat precedence rule for `connect.deploy_timeout` and
  `performance.page_load_timeout`.
- `validation_docs/demo-bot-plan-issue-288.md` — showboat demo for this PR
  (added by the implementation PR, not this plan PR).

**Modified files:**
- `src/vip/config.py` — add `TimeoutsConfig` dataclass with named semantic
  fields (see below), wire it into `VIPConfig`, parse the `[timeouts]`
  TOML section, apply the `VIP_TIMEOUT_SCALE` env var, and implement the
  precedence rule for the two backwards-compat knobs.
- `src/vip/auth.py` — replace hardcoded `timeout=10_000` / `timeout=15_000`
  / `timeout=3_000` / `timeout=2_000` literals and the `300` / `120` second
  monotonic deadlines with calls into `TimeoutsConfig`.
- `src/vip/idp.py` — replace `_FORM_TIMEOUT`, `_MFA_DETECT_TIMEOUT`,
  `_MFA_TIMEOUT` module constants and the inline `timeout=10_000`
  `wait_for_load_state` literal with `TimeoutsConfig` lookups.
- `src/vip/clients/base.py`, `src/vip/clients/connect.py`,
  `src/vip/clients/workbench.py`, `src/vip/clients/packagemanager.py` —
  thread the `TimeoutsConfig` through client constructors so the default
  `timeout=30.0` and `wait_for_task` / `wait_for_system_check` deadlines
  use config values instead of method-default literals. Existing call
  sites that pass an explicit `timeout=` keep working.
- `src/vip/verify/job.py` — use `timeouts.job_wait` for the K8s job
  deadline default in `wait_for_job` / `stream_logs` so cluster runs
  pick up the same scale.
- `src/vip_tests/conftest.py` — expose a `vip_timeouts` fixture so test
  code (and the Playwright page objects under `src/vip_tests/`) can read
  scaled values without reaching into `vip_config` directly.
- `vip.toml.example` — document the new `[timeouts]` section with every
  field, default, and a worked example using `scale = 3.0`.
- `docs/test-architecture.md` (and any other `docs/` page that mentions
  timeout knobs) — point at `[timeouts]` as the canonical location and
  describe the precedence rule for the two backwards-compat fields.

**Proposed `TimeoutsConfig` fields** (all in seconds unless noted; values
are starting points and may be tuned during implementation review):

- `scale: float = 1.0` — global multiplier applied to every other field.
  Overridable via `VIP_TIMEOUT_SCALE`.
- `http_request: float = 30.0` — default httpx client timeout.
- `connect_deploy: int = 1200` — Connect content deploy poll deadline
  (overridable via legacy `connect.deploy_timeout`).
- `connect_task_poll: float = 60.0` — `wait_for_task` deadline.
- `connect_system_check: float = 120.0` — `wait_for_system_check` deadline.
- `workbench_session_start: float = 180.0` — wait for an IDE session to
  reach "ready" after launch.
- `workbench_ide_load: float = 60.0` — wait for the IDE iframe to load.
- `playwright_form: int = 15_000` — `_FORM_TIMEOUT` (ms).
- `playwright_action: int = 10_000` — generic `wait_for_load_state` /
  `click` / `wait_for` (ms).
- `playwright_short_action: int = 3_000` — short `click` confirmations
  (ms).
- `playwright_mfa_detect: int = 10_000` — `_MFA_DETECT_TIMEOUT` (ms).
- `playwright_mfa_complete: int = 300_000` — `_MFA_TIMEOUT` (ms; 5 min).
- `playwright_page_load: float = 10.0` — overridable via legacy
  `performance.page_load_timeout`.
- `download: float = 30.0` — overridable via legacy
  `performance.download_timeout`.
- `job_wait: int = 900` — K8s Job deadline used by `verify/job.py`.

## Verification

A reviewer can confirm the change works end-to-end by running:

```bash
uv run ruff check src/ selftests/
uv run ruff format --check src/ selftests/
uv run pytest selftests/test_timeouts_config.py -v
uv run pytest selftests/ -v --ignore=selftests/test_load_engine.py
```

Plus a manual smoke test against a slow deployment:

```bash
VIP_TIMEOUT_SCALE=3 uv run vip verify --config vip.toml \
  --categories workbench -- -v -k session_start
```

Success looks like:

- The new selftest file passes (defaults, override, scale, env var,
  backwards-compat precedence).
- The full selftest suite still passes (no regressions in plugin /
  reporting / config loading).
- A `vip verify` run with `VIP_TIMEOUT_SCALE=3` exhibits 3× longer
  effective waits (visible in pytest output for a session that takes
  a long time to start), without any code change beyond the env var.
- Existing `vip.toml` files that use `connect.deploy_timeout` or
  `performance.page_load_timeout` continue to behave identically (no
  silent breaking change).

## Open questions

- UNCONFIRMED whether `playwright_mfa_complete = 5 minutes` should also be
  scaled by the global `scale`. The argument against is that this timeout
  is gated on a human entering a code, not on machine speed; scaling it
  arbitrarily lengthens a "press CTRL-C" stall when the operator walks
  away. Default proposal: do not scale — make this the one field that
  ignores `scale` and document the carve-out next to the field.
- UNCONFIRMED whether the `VIP_TIMEOUT_SCALE` env var should override the
  TOML `scale` field unconditionally or only when the TOML field is
  absent. Default proposal: env var wins (matches existing
  `VIP_CONFIG`/`VIP_CONNECT_API_KEY` semantics — env beats file).
- UNCONFIRMED whether `connect.deploy_timeout` and
  `performance.page_load_timeout` should warn when both they and the new
  `[timeouts]` field are set in the same `vip.toml`. Default proposal:
  yes, emit a `DeprecationWarning` pointing at `[timeouts]` so users
  migrate without surprise.

## Out of scope

- Changing any default timeout *value* — this PR keeps current defaults
  identical so existing fast-deployment runs are unaffected. Operators
  on slow VMs scale via `[timeouts].scale` or `VIP_TIMEOUT_SCALE`.
- Per-test overrides via pytest markers — feasible but a larger surface
  change; can follow as a separate issue if requested.
- Adjusting K8s `activeDeadlineSeconds` for the verify Job from the CLI
  flag `--timeout`. That flag stays as the user-facing knob for the Job
  itself; `timeouts.job_wait` only affects the in-process `stream_logs` /
  `wait_for_job` polling deadlines.
- Renaming or removing `ConnectConfig.deploy_timeout` /
  `PerformanceConfig.page_load_timeout`. They stay for compatibility;
  deprecation can land in a later release after migration data is in.
