# Plan for issue #388: workbench session cold-start timeout default

## Context

Live validation of a Posit Team staging deployment surfaced a recurring
flake: `TIMEOUT_SESSION_START` (currently `90_000` ms = 90 s) consistently
fires before a Workbench session cold-start reaches Active. The reporter
observed real cold-start latencies past **360 s**, and the only way to
get scenarios green was to set `VIP_TIMEOUT_SCALE=3` (or 5). Issue #368
already validated that the scale knob does the right thing end-to-end —
the lever exists, but operators don't discover it until after they hit
the wall.

The issue presents two non-exclusive options:

1. **Raise the default `TIMEOUT_SESSION_START`** so first-run experience
   on slow / cold deployments stops timing out before the platform has a
   chance to spin a session up.
2. **Document `VIP_TIMEOUT_SCALE` more prominently** so that when the
   raised default is *still* not enough on a particularly slow VM, the
   operator's next step is obvious instead of "open a github issue".

The cleanest answer is to do **both**, in proportion: a measured bump of
the session-start default that swallows the common case, plus a
top-level pointer to `VIP_TIMEOUT_SCALE` for the long tail. We
deliberately do **not** raise the default to 360 s — that punishes every
fast deployment with a 6-minute wait whenever a real failure occurs, and
the existing scale lever already covers the long tail without that cost.

## Architecture

This is a one-module-plus-docs change. The substantive code change is a
literal edit in `src/vip_tests/workbench/conftest.py` where the timeout
constants live. Nothing about the timeout-scale pipeline (`src/vip/timeouts.py`)
needs to move — it was designed exactly so that adjusting any literal
keeps the multiplier semantics intact (issue #288, plan
`2026-06-01-issue-288-timeout-configuration.md`).

The four-layer architecture is unaffected: this is a Layer-3 default
adjustment that flows transparently to every Layer-1 step that calls
`wait_for_session_active(...)` or imports `TIMEOUT_SESSION_START`.

### Sizing the new default

| Default | Covers cold-starts up to | Wait-on-failure penalty |
|---|---|---|
| 90 s (current) | nominal hardware | minimal, but flakes on slow VMs |
| **180 s** (proposed) | most slow-VM cases | +90 s on a real failure |
| 300 s | nearly all observed cases | +210 s — too punitive |
| 360 s | all observed cases incl. the worst | +270 s — unacceptable |

180 s is the sweet spot: it absorbs the *typical* slow-VM case (where
`VIP_TIMEOUT_SCALE=2` would have rescued it), and the long tail
(`>180 s` cold-starts, where the reporter saw `>360 s`) still has
`VIP_TIMEOUT_SCALE=3` as the explicit, documented escape hatch. Selftest
`test_constants_scale_on_reload` already pins `TIMEOUT_SESSION_START ==
180_000` at `VIP_TIMEOUT_SCALE=2` — moving the unscaled default to 180 s
re-uses that arithmetic anchor and keeps the scale-2 expectation at
360 s without changing the helper.

`TIMEOUT_IDE_LOAD` (currently 60 s) is **deliberately left alone** in
this plan — the reporter named session-start specifically, and IDE load
sits behind the same network. Opening the IDE-load default is a
separate decision that should be informed by its own validation data;
flagged below as an out-of-scope follow-up rather than bundled here.

## Components

### `src/vip_tests/workbench/`

- **`conftest.py`** — change the literal:
  `TIMEOUT_SESSION_START = int(180_000 * timeout_scale())` (was
  `90_000`). Update the surrounding comment block to record the rationale
  ("180 s absorbs typical slow-VM cold-starts; longer waits should use
  `VIP_TIMEOUT_SCALE`"). No other constants change.

### `selftests/`

- **`test_timeouts.py`** — update
  `TestWorkbenchConftestConstants::test_constants_default_at_scale_one`
  to assert `TIMEOUT_SESSION_START == 180_000` (was `90_000`) and
  `test_constants_scale_on_reload` to assert
  `TIMEOUT_SESSION_START == 360_000` at `VIP_TIMEOUT_SCALE=2` (was
  `180_000`). The existing tests already exercise the reload-on-scale
  pathway; this just retunes the numbers.

### Docs / discoverability

- **`README.md`** — add a one-paragraph "Slow deployments" callout under
  *Quick start* (or *CLI commands*) that names `VIP_TIMEOUT_SCALE` with a
  worked example: `VIP_TIMEOUT_SCALE=3 vip verify --connect-url …`.
  Link out to `docs/test-architecture.md#tuning-timeouts-on-slow-hardware`
  for the full list of what the scale covers and what it deliberately
  doesn't. Keep it tight — operators read README first, that's the whole
  point of moving this knob into it.
- **`vip.toml.example`** — promote the existing `VIP_TIMEOUT_SCALE`
  comment block (lines 178–183 today) out of the `[load_test]` tail and
  into a top-of-file comment near where credentials are described.
  Lower-traffic location is currently muting it.
- **`website/src/pages/getting-started.astro`** — mirror the README
  callout so the published docs surface the lever in the same first-read
  flow. (The `docs/*.md` shims point here.)

### Out of this plan (deliberately)

- Bumping `TIMEOUT_IDE_LOAD`, `TIMEOUT_PAGE_LOAD`, or any other
  Playwright literal. Each one is a separate validation question.
- Adding a per-test override mechanism (e.g. `@pytest.mark.slow_session`)
  — `VIP_TIMEOUT_SCALE` is the agreed lever per #288, and this issue is
  not asking for finer granularity.
- A "suggest `VIP_TIMEOUT_SCALE`" hint in the timeout error message.
  Worth doing eventually, but it lives in the Playwright wait helpers
  (and the Quarto report) and would more than double this PR's surface
  area; better as a follow-up issue.

## Verification

After implementation, a reviewer should:

1. **Selftests pass with the new default**:
   ```bash
   uv run pytest selftests/test_timeouts.py -v
   ```
   Expect both `test_constants_default_at_scale_one` and
   `test_constants_scale_on_reload` green.

2. **Lint / format clean**:
   ```bash
   uv run ruff check src/ src/vip_tests/ selftests/ examples/
   uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
   ```

3. **Workbench step files pick up the new constant** (sanity, no
   product needed):
   ```bash
   uv run python -c "from vip_tests.workbench.conftest import TIMEOUT_SESSION_START; assert TIMEOUT_SESSION_START == 180_000; print(TIMEOUT_SESSION_START)"
   VIP_TIMEOUT_SCALE=3 uv run python -c "from vip_tests.workbench.conftest import TIMEOUT_SESSION_START; assert TIMEOUT_SESSION_START == 540_000; print(TIMEOUT_SESSION_START)"
   ```

4. **README and website page** mention `VIP_TIMEOUT_SCALE` in their
   first-read flow, with a working command example. Spot-check that the
   link from the README callout resolves to the existing
   `docs/test-architecture.md` heading.

5. **No collateral damage** to product tests: `vip verify --collect-only`
   continues to enumerate the same scenarios it did before (the
   constant move does not change collection).

A showboat demo on the implementation PR should run the
`selftests/test_timeouts.py` subset and capture the constants at scale 1
and 3 (per AGENTS.md guidance to scope demos narrowly to avoid
unrelated flakes).

## Open questions

- UNCONFIRMED: whether 180 s actually absorbs *most* slow-deployment
  cases or just the median. The reporter saw `>360 s` worst-case; if
  the staging fleet's p90 is also `>180 s`, we should consider 240 s
  instead. Implementation should check the validation logs from #368
  before locking the number in.
- UNCONFIRMED: whether the `vip.toml.example` callout move belongs in
  this PR or in a dedicated docs PR. Bundling keeps the change atomic;
  splitting keeps the diff small. Reviewer's call.

## Out of scope

- Any change to `src/vip/timeouts.py` — the helper is correct as-is and
  ships with comprehensive selftests already.
- Any change to `.github/workflows/**` or release automation — defaults
  bump is a behaviour change for end-users, not for CI.
- Migrating other `TIMEOUT_*` constants to a config-driven taxonomy —
  explicitly rejected in plan
  `2026-06-01-issue-288-timeout-configuration.md` and not revisited
  here.
