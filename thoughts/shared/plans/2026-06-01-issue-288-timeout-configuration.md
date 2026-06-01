# Plan for issue #288: improved timeout configuration

## Context

VIP currently exposes only a small handful of timeout knobs (`ConnectConfig.deploy_timeout`, `PerformanceConfig.page_load_timeout`, `PerformanceConfig.download_timeout`) while dozens of timeouts live as bare literals scattered across `src/vip/auth.py`, the four httpx clients in `src/vip/clients/`, the Playwright fixtures in `src/vip_tests/workbench/conftest.py`, and the Kubernetes job runner in `src/vip/verify/job.py`. Operators running Marketplaces / QA deployments on small VMs hit those literals as flaky timeouts that they cannot tune from `vip.toml`.

The goal of this change is to (a) inventory every timeout in the codebase, (b) consolidate them under a new top-level `[timeouts]` config section with semantic per-operation fields, (c) introduce a single `scale` multiplier (plus matching `VIP_TIMEOUT_SCALE` env var) so operators can dilate every timeout uniformly without editing source, and (d) preserve the existing knobs as overrides so no current `vip.toml` becomes invalid.

## Architecture

The change lands in three layers, mirroring the four-layer test architecture from `docs/test-architecture.md`:

1. **Config model** (`src/vip/config.py`) — a new `TimeoutConfig` dataclass holds semantic fields in seconds (`http_request`, `connect_deploy`, `connect_task_wait`, `connect_system_check_wait`, `workbench_page_load`, `workbench_dialog`, `workbench_session_start`, `workbench_ide_load`, `workbench_code_exec`, `workbench_session_capacity_quick`, `workbench_session_capacity_cleanup`, `playwright_oidc_complete`, `playwright_mfa_complete`, `job_wait`, `tcp_probe`, `download`). The dataclass exposes `scale: float = 1.0` and a helper `effective(field) -> float` that returns `getattr(self, field) * scale`. Loaded via `TimeoutConfig.from_dict` from a new `[timeouts]` table in `vip.toml`. `VIPConfig` gains a `timeouts: TimeoutConfig` attribute.

2. **Bridge to existing per-section knobs** — `ConnectConfig.deploy_timeout` and `PerformanceConfig.page_load_timeout` / `download_timeout` stay as fields, but their `from_dict` resolution becomes: explicit value in the section → matching `[timeouts]` value → built-in default. This means the new `[timeouts]` table is the central place to set values, while old `vip.toml` files (with `deploy_timeout` under `[connect]`) keep working unchanged.

3. **Consumers** — every literal timeout in production code is replaced with a read from `vip_config.timeouts.effective("<field>")` (or the equivalent millisecond-scaled module-level constants in `src/vip_tests/workbench/conftest.py`, which already centralises Playwright timeouts). Test-suite fixtures expose a `timeouts` fixture so step files can write `timeouts.workbench_session_start` instead of hardcoded module constants.

A new selftest `selftests/test_timeouts.py` covers config parsing, scale arithmetic, env-var override, and the precedence rule (`[connect].deploy_timeout` wins over `[timeouts].connect_deploy`).

## Components

**New files:**

- `src/vip/timeouts.py` — small helper module exposing `TimeoutConfig`, `effective()`, and the `VIP_TIMEOUT_SCALE` env-var resolver. (Kept separate from `config.py` to keep the config module readable; `config.VIPConfig` re-exports it.)
- `selftests/test_timeouts.py` — covers (1) defaults, (2) per-field override via TOML, (3) `scale=2.0` doubles every effective value, (4) `VIP_TIMEOUT_SCALE` env var beats the file value, (5) `connect.deploy_timeout` wins over `timeouts.connect_deploy`, (6) unknown `[timeouts]` keys raise `ConfigError`.
- `validation_docs/demo-bot-plan-issue-288.md` — showboat demo running the new selftests and `ruff check`.

**Modified files:**

- `src/vip/config.py` — add `TimeoutConfig` dataclass, wire it into `VIPConfig.from_dict`, and update `ConnectConfig.from_dict` / `PerformanceConfig.from_dict` to consult the timeouts section as fallback.
- `src/vip/auth.py` — replace the eight literal timeouts (3_000 ms click, 10_000 / 15_000 ms locator waits, the 300 s and 120 s deadlines, the 5_000 ms networkidle wait, the 500 ms poll sleep, the 10.0 s httpx waits) with `timeouts.effective(...)` reads.
- `src/vip/clients/base.py`, `connect.py`, `workbench.py`, `packagemanager.py` — the `timeout: float = 30.0` constructor default becomes `timeout: float | None = None`, resolved at call sites from `vip_config.timeouts.effective("http_request")`. Internal helpers `wait_for_task` (default 60 s) and `wait_for_system_check` (default 120 s) gain matching defaults from `connect_task_wait` / `connect_system_check_wait`.
- `src/vip/verify/job.py` — replace its hardcoded job-wait timeout with `timeouts.effective("job_wait")`.
- `src/vip_tests/conftest.py` — expose a `timeouts` fixture that returns `vip_config.timeouts` for step files to consume.
- `src/vip_tests/workbench/conftest.py` — replace the module-level millisecond constants (`TIMEOUT_QUICK`, `TIMEOUT_DIALOG`, `TIMEOUT_PAGE_LOAD`, `TIMEOUT_IDE_LOAD`, `TIMEOUT_SESSION_START`, `TIMEOUT_CLEANUP`, `TIMEOUT_CODE_EXEC`) with values computed from the `timeouts` fixture (×1000 for ms). Step files keep importing the constants and need no change.
- `vip.toml.example` — add a fully-commented `[timeouts]` section showing every field at its default plus the `scale = 1.0` knob, with a worked example that doubles all timeouts for QA VMs.
- `docs/test-architecture.md` — short subsection ("Tuning timeouts") pointing operators at the new `[timeouts]` section, the `scale` multiplier, and the `VIP_TIMEOUT_SCALE` env var, plus the precedence rule.

## Verification

A reviewer can confirm the change works end-to-end with:

```bash
# 1. Lint and unit tests must pass.
uv run ruff check src/ src/vip_tests/ selftests/ examples/
uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
uv run pytest selftests/test_timeouts.py -v

# 2. Existing selftests must still pass — no regressions in config loading.
uv run pytest selftests/ -v

# 3. Dry-collect product tests to make sure the new fixture doesn't break collection.
uv run pytest src/vip_tests/ --collect-only -q

# 4. Smoke-test the scale knob with a temporary config.
VIP_TIMEOUT_SCALE=2 uv run python -c "from vip.config import load_config; c = load_config('vip.toml.example'); print(c.timeouts.effective('connect_deploy'))"
# Expect: 2400.0  (default 1200 × scale 2)
```

Success looks like: the new selftests pass, the existing 240+ selftests still pass, product-test collection still works, and the smoke-test prints `2400.0`.

## Open questions

- **UNCONFIRMED — should `playwright_mfa_complete` be excluded from the global `scale`?** The 5-minute MFA prompt window in `src/vip/auth.py` is a human wait, not a server wait, so scaling it for slow VMs is meaningless. Proposal: add a `scale_excludes: list[str]` field (default `["playwright_mfa_complete"]`) and skip those keys in `effective()`. Maintainer to confirm.
- **UNCONFIRMED — env-var precedence.** Plan above has `VIP_TIMEOUT_SCALE` beat the file value. The alternative (file wins) matches `VIP_CONNECT_API_KEY` precedence. Maintainer to pick.
- **UNCONFIRMED — deprecation warning for `connect.deploy_timeout`.** We could emit a `DeprecationWarning` directing users to `[timeouts]`, or keep both indefinitely. Plan above keeps both indefinitely with no warning to avoid noise during the transition.

## Out of scope

- Per-test-case timeout overrides via pytest markers — too fine-grained; semantic config fields cover the real use cases.
- Retries / exponential backoff — the issue is about timeout duration, not retry policy.
- Touching CI workflow timeouts under `.github/workflows/` — those are GitHub Actions-level and outside this code's reach (and forbidden by the agent's denylist).
- Async / streaming timeouts on long-running deploy log tailing — those use heartbeat-based liveness, not a fixed timeout, and are unaffected.
