# Design — #409: More robust CI/CD for 1.0 (epic)

**Status:** Approved design (brainstorming) — epic; Child A ready for implementation plan
**Date:** 2026-06-30
**Issue:** posit-dev/vip#409
**Dispatch order:** AFTER #411 merges (parallel with #410)

## Framing

#409 is an **epic**, not a single PR. "Robust CI/CD" is not greenfield — VIP already has
`ci.yml` (lint / mypy / zizmor / dependency audit / selftests / `--collect-only` dry run)
plus a fleet of smoke workflows (`connect-smoke`, `workbench-smoke`, `packagemanager-smoke`,
`mac-smoke`, `linux-smoke`, `connect-integration`, `docker`). This epic fills the gaps that
1.0 needs, decomposed into four children, each its own issue / spec / PR.

## Child A — Mock-IdP E2E suite  (PRIMARY — define + implement first)

**Goal:** exercise the auth flows in CI without a real IdP.

- Stand up a **containerized real Keycloak** (docker service / compose) with a seeded
  realm, test users, and TOTP — **fronting BOTH Connect and Workbench** (both products'
  OIDC paths; `auth.py` already accepts Connect or Workbench URLs).
- E2E-test:
  - `--headless-auth` — fully automatable in CI via the `idp.py` Keycloak strategy +
    `VIP_TEST_TOTP_SECRET`.
  - `--interactive-auth` **state machine** — the human-click SSO step driven/stubbed by
    Playwright so the non-headless flow is still covered.
- New **gated** CI job (not `--collect-only`). Reuse the **repurposed root `Dockerfile`**
  (preserved by #411) as the runner image.

**Child A acceptance:** mock-IdP E2E job green in CI against both Connect and Workbench,
with no real IdP; covers headless + interactive auth state machines.

## Child B — Workbench version matrix
Run Child A's E2E (and the product suite) across multiple Workbench container versions to
catch version-specific auth/UI regressions. **Directly consumes #410's versioned page
objects** — the matrix run instantiates the right page objects per version.

## Child C — Real-product integration in CI
Promote the existing `*-smoke.yml` workflows from `--collect-only` dry runs into gated
integration runs against containerized Connect / Workbench / PM.

## Child D — Release/publish hardening
Harden `release.yml` / `publish.yml` / `docker.yml`: artifact provenance + signing,
smoke-test the published package, 1.0 version-bump correctness.

## Dependencies
- **#411 first** — removes K8s mode (independent of auth, confirmed) and preserves the
  root `Dockerfile` for Child A to repurpose.
- **#410** — Child B depends on the versioned page objects from #410.

## Epic acceptance criteria
- Each child tracked as its own issue with its own acceptance criteria.
- Child A (mock-IdP E2E) green in CI without any real IdP — the concrete 1.0 deliverable.
- B / C / D scoped as well-defined follow-on issues (stubs expanded when their turn comes).
