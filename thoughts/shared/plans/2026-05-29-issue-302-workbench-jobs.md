# Plan for issue #302: Add Workbench Jobs and Background Jobs test coverage

## Context

A customer mapped their UAT test plan against VIP and identified Workbench Jobs as a gap. Both Workbench Jobs (run on separate Kubernetes pods via Launcher) and Background Jobs (run in the same session) are first-class Workbench features that customers exercise during acceptance testing. Currently `src/vip_tests/workbench/` has no job-related scenarios — tests cover session launch, suspend/resume, and capacity, but never submit scripts as jobs. This change adds BDD coverage for both job types to validate deployment functionality that customers depend on.

## Architecture

The new tests live in `src/vip_tests/workbench/` alongside existing session and auth tests. They use Playwright to drive the RStudio Pro UI, submitting jobs via the Jobs pane and Background Jobs pane respectively. The Workbench Jobs scenario indirectly validates Launcher infrastructure (a useful side effect). Tests follow the four-layer architecture: Gherkin feature → step definitions → Playwright UI automation → browser driver.

## Components

**src/vip_tests/workbench/**
- `test_jobs.feature` — new Gherkin file with two scenarios (Workbench Job, Background Job), tagged `@workbench`
- `test_jobs.py` — step definitions using `pytest_bdd`, Playwright page fixtures, and `target_fixture` for state passing

**Test artifacts**
- Inline test R script (e.g. `Sys.sleep(2); cat("hello from job\n")`) written to session working directory via RStudio Console or file API
- Job cleanup in final `then` step to remove artifacts

## Verification

Run the new tests against a live Workbench deployment:

```bash
uv run vip verify --config vip.toml --categories workbench -- -k "Jobs" -v
```

Success looks like:
- Both scenarios pass (Workbench Job reaches Completed, Background Job shows Completed in pane)
- Job logs contain expected output (`hello from job`)
- No leftover job artifacts remain after cleanup
- Lint passes: `uv run ruff check src/vip_tests/workbench/`

## Open questions

**UNCONFIRMED**: Does the Background Jobs scenario require different Playwright selectors than Workbench Jobs, or can we reuse the same page object pattern? This depends on RStudio Pro's UI structure — will be resolved during implementation by inspecting the DOM.

Job submission timeout should be **configurable** (not hardcoded). This allows adapting to varying network latency or cluster load without code changes.

**UNCONFIRMED**: The issue mentions "depends on the in-session execution primitive (separate issue) only for writing the script file". Should this plan wait for that primitive, or implement script writing inline? Propose writing the script via RStudio Console (`writeLines(c(...), "test_job.R")`) for now — the primitive can refactor it later if needed.

## Out of scope

- Verifying specific Launcher pod resource limits or Kubernetes node placement — those are infrastructure concerns beyond VIP's acceptance scope.
- Testing job cancellation or error handling — the initial scenarios cover happy-path only. Failure modes can be added in a follow-up if customers request them.
- Package installation within jobs — that's covered by existing package manager tests.
- Parallel job submission or concurrency limits — out of scope for initial coverage.
