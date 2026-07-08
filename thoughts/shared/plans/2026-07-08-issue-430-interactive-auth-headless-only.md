# Issue #430 — `--interactive-auth` E2E: headless-only stance

**Date:** 2026-07-08
**Issue:** [posit-dev/vip#430](https://github.com/posit-dev/vip/issues/430) (child of #409 robust CI/CD epic)
**Status:** Decided — will *not* automate `--interactive-auth` E2E.

## The fork

#430 followed from #409 Child A (#419), which shipped the mock-IdP E2E suite:
`--headless-auth` runs end-to-end against a seeded Keycloak realm fronting real
Connect and Workbench containers (`compose.mock-idp.yml`, `mock-idp-e2e.yml`).
`--interactive-auth` E2E was deferred, and #430 posed the choice: automate it, or
decide it is not worth the fragility and document a headless-only stance.

## Decision

**Headless-only.** We do not automate `--interactive-auth` in CI. The marginal
coverage does not justify the orchestration fragility, and the automation would
largely test scaffolding rather than production code.

## Why

**What `--interactive-auth` actually is.** `start_interactive_auth`
(`src/vip/auth.py:369`) launches a *headed* Chromium (`headless=False`), navigates
to the product login page, then **blocks**, polling the page URL for up to five
minutes waiting for a *human* to click through the IdP (`src/vip/auth.py:439-470`).
It contains no form-filling of its own — the human is the driver. That is the
defining difference from `--headless-auth`, which fills the Keycloak form itself
via `vip.idp` and is already exercised end-to-end in `mock-idp-e2e.yml`.

**What automating it would require.** Because the function blocks on a human, a CI
automation would need, concurrently:

1. Xvfb — GitHub's `ubuntu-latest` runners are headless, but this code path
   insists on a headed browser.
2. `vip verify --interactive-auth` blocking in one process.
3. A **second driver process attaching over CDP** to that Chromium to fill the
   Keycloak username/password/TOTP form so the URL changes and the poll loop in
   process 1 unblocks.

**Why the coverage is thin.** The second process's form-filling is *test
scaffolding* — in production a human does it, so that code exercises nothing that
ships. The only production code uniquely on the interactive path is: the headed
launch, the poll-loop login-detection (`src/vip/auth.py:442-464`), and the
OIDC-confirm click. The real-IdP round-trip, TLS trust, API-key minting, and
Workbench SSO cookie capture are all shared with `--headless-auth` and already
covered by the headless E2E job. So a fragile dual-process CDP + Xvfb + TOTP-timing
harness — maintained on every relevant CI run — would buy coverage of only the
headed launch and the poll-loop URL heuristics.

**Better spent on unit coverage.** Those poll-loop URL heuristics are exactly what
a unit test can pin down deterministically, with no browser at all. That is where
we invest instead (see below).

## Safety net

- **Headless E2E** (`mock-idp-e2e.yml`) covers the shared machinery against a real
  seeded Keycloak: OIDC round-trip, TLS/CA trust, API-key mint, Workbench SSO.
- **Unit tests** (`selftests/test_auth.py`) cover the interactive-unique logic.
  This change closes the one real gap: prior to it, the interactive poll loop's
  own success/timeout detection had no direct test — the existing
  `test_timeout_during_login_becomes_auth_config_error` covers `start_headless_auth`
  (via the shared `_wait_for_product_redirect` helper), not the separate inline
  loop inside `start_interactive_auth`. We add tests for:
  - Connect success — URL leaves `/__login__`.
  - Workbench success — URL is no longer on a `sign-in`/`login`/`auth` page.
  - Timeout — the loop never detects completion and raises `RuntimeError`.

## Scope

In scope:

1. Add the interactive poll-loop unit tests above (`selftests/test_auth.py`).
2. Reword the `mock-idp-e2e.yml` comment (its current "deferred as follow-up work"
   note) to record this as a settled headless-only decision pointing here.
3. This decision record.
4. Close #430 with a summary linking the decision and the new tests.

Out of scope (YAGNI):

- No website/end-user docs change — the user-facing docs already explain
  interactive vs. headless usage; the CI stance is a maintainer concern and the
  workflow comment is its discoverable home.
- No refactor to merge the two poll loops into `_wait_for_product_redirect` — the
  behaviors differ (headless raises on timeout; interactive additionally detects
  Connect's `/__login__` boundary), so merging adds more risk than value here.

## Revisiting

Reopen this decision if `start_interactive_auth` gains its own form-filling (making
the interactive path automatable without a second CDP process), or if a regression
escapes both the headless E2E and these unit tests.
