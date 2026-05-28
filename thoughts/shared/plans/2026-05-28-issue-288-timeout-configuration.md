# Plan for issue #288: Improved timeout configuration

## Context

VIP tests against Posit Team deployments (Connect, Workbench, Package Manager) on varied infrastructure. Smaller QA environments with limited VM resources experience extended load times — session launches, content deployments, and package operations can take significantly longer than on production-sized hardware. Currently, only three timeouts are configurable (`deploy_timeout` in Connect, `page_load_timeout` and `download_timeout` in Performance), while dozens more are hardcoded across the test suite. Users testing on resource-constrained infrastructure must either accept test failures or fork VIP to adjust the timeouts. This enhancement provides a centralized, comprehensive timeout configuration that scales up or down based on environment characteristics.

## Architecture

Timeout configuration lives in `src/vip/config.py` as a new `TimeoutConfig` dataclass nested under the root `VIPConfig`. The config loader reads `[timeouts]` section from `vip.toml` and merges with defaults. Each timeout has a semantic name (`session_start`, `ide_load`, `deploy_complete`, etc.) rather than product-specific prefixes.

Four subsystems consume timeout values:
- `src/vip/auth.py` — browser login flows, IdP page waits
- `src/vip/clients/` — httpx request timeouts, task polling intervals
- `src/vip_tests/workbench/conftest.py` — Playwright waits (currently hardcoded constants)
- `src/vip_tests/connect/` — deploy polling, package install waits

The timeout config is injected via a new `timeout_config` pytest fixture in `src/vip_tests/conftest.py`.

## Components

**Add:**
- `src/vip/config.py` — `TimeoutConfig` dataclass with ~15 semantic timeout fields (seconds or milliseconds as appropriate), `from_dict` method, and integration into `VIPConfig.from_dict`

**Modify:**
- `src/vip_tests/conftest.py` — add `timeout_config` fixture returning `vip_config.timeouts`
- `src/vip_tests/workbench/conftest.py` — replace hardcoded `TIMEOUT_*` constants with expressions using `timeout_config` (e.g., `TIMEOUT_SESSION_START = timeout_config.session_start_ms`)
- `src/vip/auth.py` — replace hardcoded `timeout=10_000`, `timeout=3_000` with `timeout_config` references
- `src/vip/clients/base.py` — thread `timeout_config` through constructor, use for default httpx timeout
- `src/vip/clients/connect.py` — use `timeout_config.deploy_timeout` in `wait_for_task`
- `vip.toml.example` — add `[timeouts]` section with inline comments explaining each field

**Selftests:**
- `selftests/test_config.py` — add `test_timeout_config_from_dict` to verify TOML parsing, defaults, and field types

## Verification

Run the new selftest:
```bash
uv run pytest selftests/test_config.py::test_timeout_config_from_dict -v
```

Confirm the example config parses without error:
```bash
uv run python -c "from vip.config import VIPConfig; import tomli; VIPConfig.from_dict(tomli.load(open('vip.toml.example', 'rb')))"
```

Integration verification requires a running Workbench or Connect instance. Create a minimal `vip.toml` with doubled timeout values and run a subset of session tests to confirm no hardcoded timeout failures.

## Open questions

- **Milliseconds vs. seconds**: Playwright expects milliseconds; httpx expects seconds. The config can store both (e.g., `session_start_s` and `session_start_ms`) or store seconds and multiply by 1000 at use sites. Storing milliseconds for browser waits and seconds for HTTP is clearer.
- **Timeout multiplier**: An alternate design is a single `timeout_scale_factor` (default 1.0) that multiplies all hardcoded values at runtime. This is simpler but less granular. The per-timeout approach is preferred for flexibility.
- **Backwards compatibility**: Moving `deploy_timeout` from `[connect]` to `[timeouts]` is a breaking change. UNCONFIRMED whether to deprecate the old location or support both during a transition period.

## Out of scope

- **Adaptive timeout scaling** based on measured latency — a future enhancement could auto-detect slow environments and scale timeouts accordingly. This plan provides the configuration foundation only.
- **Timeout profiling report** — capturing actual wait times and comparing to configured limits. Useful for tuning but not required for the initial rollout.
- **Per-test timeout overrides** via pytest markers — the configuration is global. Tests that genuinely need different limits can still use local values.
