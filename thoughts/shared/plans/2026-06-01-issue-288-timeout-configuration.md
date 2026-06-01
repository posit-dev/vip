# Plan for issue #288: improved timeout configuration

## Context

VIP currently runs against Posit Team deployments where load behavior
varies wildly with VM size. On QA / Marketplaces instances backed by
small VMs, operations like Workbench session start, Connect content
deploy, and Package Manager mirror traversal routinely take longer
than VIP's hardcoded waits, causing spurious failures that have to be
investigated as if they were product regressions.

Today, only a handful of timeouts are configurable (`deploy_timeout`
under `[connect]`, `page_load_timeout` / `download_timeout` under
`[performance]`, and the CLI's `--test-timeout` / `--timeout`). The
rest are scattered as numeric literals across `src/vip/auth.py`,
`src/vip/idp.py`, `src/vip/clients/*.py`, and `src/vip/verify/job.py`
(see `_FORM_TIMEOUT`, `_MFA_DETECT_TIMEOUT`, the various
`timeout=10_000` Playwright calls, and the default `timeout=30.0` on
every httpx client).

The goal is to give operators a single, well-documented place to scale
timeouts up (slow QA VM) or down (fast prod-sized box) without editing
source, while keeping the existing defaults unchanged for users who do
not opt in.

## Architecture

The change lives entirely in the configuration + client layers — no
changes to feature files or step definitions. Two pieces:

1. A new `TimeoutsConfig` dataclass in `src/vip/config.py`, alongside
   the existing `PerformanceConfig`. It holds named, semantic
   timeouts (e.g. `http_request`, `connect_deploy`, `workbench_session_start`,
   `playwright_form`, `playwright_mfa_detect`, `playwright_mfa_complete`,
   `playwright_page_load`, `job_wait`, `job_log_stream`) plus a single
   `scale: float = 1.0` multiplier applied to every value at access time.
2. A loader path that reads `[timeouts]` from `vip.toml`, env-var
   overrides for the most-common knobs (e.g. `VIP_TIMEOUT_SCALE`), and
   threads the resulting `TimeoutsConfig` through `VIPConfig` so
   clients and Playwright helpers can read named values instead of
   literals.

Existing per-section timeouts (`ConnectConfig.deploy_timeout`,
`PerformanceConfig.page_load_timeout`/`download_timeout`) stay where
they are for backwards compatibility, but `TimeoutsConfig` becomes the
authoritative source for everything currently hardcoded. A migration
note is added to `vip.toml.example`.

## Components

Files to add or modify:

- `src/vip/config.py` — add `TimeoutsConfig` dataclass with `scale`
  multiplier and a `get(name) -> float` helper that returns the scaled
  value; wire it into `VIPConfig.from_dict` under `[timeouts]`; honor
  `VIP_TIMEOUT_SCALE` env var.
- `src/vip/idp.py` — replace `_FORM_TIMEOUT`, `_MFA_DETECT_TIMEOUT`,
  `_MFA_TIMEOUT`, and the inline `timeout=10_000` / `timeout=5_000`
  calls with lookups from a `TimeoutsConfig` passed in by the caller.
  Keep the existing module constants as fallback defaults so unit
  tests that import them keep working.
- `src/vip/auth.py` — replace the magic numbers in
  `_authenticate_workbench` and helpers (e.g. `timeout=10_000`,
  `timeout=15_000`, the `300`-second deadline for MFA, the `120`-second
  Workbench-load deadline) with `TimeoutsConfig` lookups.
- `src/vip/clients/{base,connect,workbench,packagemanager}.py` —
  accept an optional `TimeoutsConfig` and use `timeouts.http_request`
  as the default for the `httpx` client and `timeouts.connect_task_wait`
  / `timeouts.connect_system_check` for `wait_for_task` and
  `wait_for_system_check`.
- `src/vip/verify/job.py` — use `timeouts.job_wait` and
  `timeouts.job_log_stream` instead of the `840` / `900` literals.
- `src/vip_tests/conftest.py` — expose a `timeouts` fixture and
  thread it into the existing client fixtures.
- `vip.toml.example` — add a documented `[timeouts]` section showing
  the available fields and the global `scale` knob, plus a comment
  pointing at `VIP_TIMEOUT_SCALE`.
- `selftests/test_timeouts_config.py` (new) — covers default values,
  per-field overrides, the `scale` multiplier, the `VIP_TIMEOUT_SCALE`
  env var, and that unknown keys raise.
- `docs/configuration.md` (if present, otherwise extend `README.md`) —
  document the new section with a "slow VM" recipe (`scale = 3.0`).

## Verification

A reviewer can confirm the change works as follows:

```bash
# 1. New unit tests pass and cover the new surface.
uv run pytest selftests/test_timeouts_config.py -v

# 2. Existing selftests still pass — no regression in config loading.
uv run pytest selftests/ -v

# 3. Lint / format clean.
uv run ruff check src/ src/vip_tests/ selftests/ examples/
uv run ruff format --check src/ src/vip_tests/ selftests/ examples/

# 4. Manual smoke: with VIP_TIMEOUT_SCALE=3 set, the resulting config
#    object reports 3x values for every named timeout.
VIP_TIMEOUT_SCALE=3 uv run python -c \
  "from vip.config import load_config; c = load_config('vip.toml.example'); \
   print(c.timeouts.get('http_request'), c.timeouts.get('connect_deploy'))"
```

Success looks like: defaults unchanged when no `[timeouts]` section is
present; per-field values overridden when set; every value multiplied
by `scale` (or `VIP_TIMEOUT_SCALE`) when supplied; and the existing
`deploy_timeout` / `page_load_timeout` keys continue to work via a
small shim that copies them into the new `TimeoutsConfig` if the new
section is absent.

## Open questions

- UNCONFIRMED: whether to keep `ConnectConfig.deploy_timeout` and
  `PerformanceConfig.page_load_timeout` as the canonical home for
  those two values (with `[timeouts]` reading from them) or to deprecate
  them in favor of `[timeouts]`. Initial implementation will keep both
  with a precedence rule: `[timeouts]` wins if set, otherwise the
  existing per-section field.
- UNCONFIRMED: whether the `scale` knob should be a single float or a
  per-category dict (e.g. `scale = { http = 1.0, playwright = 3.0 }`).
  A single float is simpler; the dict form can be added later without
  breaking the simple form.
- UNCONFIRMED: whether to add a `[timeouts.workbench]` and
  `[timeouts.connect]` namespace for product-specific groupings or
  keep flat keys. Flat keys are easier to document; namespacing is
  easier to extend. Leaning flat for v1.

## Out of scope

- Changing any product test feature files or step definitions —
  this is a configuration / plumbing change only.
- Reworking the load-test (locust / async) timeouts under
  `PerformanceConfig.load_*` — those have their own semantics
  (duration, spawn rate) and are not "I waited too long for this op"
  timeouts.
- Adding retry / backoff policies. This plan only covers the
  deadline/wait values; smarter retry behavior is a separate effort.
- Touching `.github/workflows/**` or the `vip install` manifest —
  no CI or installer changes are needed.
