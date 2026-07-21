# Design — #484: parallelize Workbench tests by hybrid grouping + login lock

**Status:** Approved design (brainstorming) — ready for implementation plan
**Date:** 2026-07-20
**Issue:** posit-dev/vip#484 (part of epic #480)

## Problem

Under `--interactive-auth` / `--headless-auth` all Workbench tests authenticate as the
**same shared account** and are pinned to a single xdist worker
(`src/vip_tests/workbench/conftest.py::pytest_collection_modifyitems`, the
`workbench_interactive_serial` group). The result is a fully **serial** ~10-minute run.

The pin exists to avoid an OIDC **login storm**: because Playwright's `page`/`context` are
function-scoped and every worker loads the *same* shared `storage_state` file (which holds
only IdP cookies, not an established Workbench session), **every test** does its own silent
SSO round-trip (`workbench_login` → click "Sign in with OpenID", `conftest.py:391-411`).
Many workers doing that round-trip against the one shared IdP session simultaneously makes
the IdP bounce sessions back to the sign-in page (the `?error=2` flakiness from #467
validation).

For password auth (no shared session) Workbench already runs parallel — the serialization
is purely the OIDC-login-storm workaround.

## Scope (from design chat)

**In:**
- Replace the single-worker pin with parallel-by-group execution, **only** when a shared
  auth session is active (the existing `_auth_session_key` gate is preserved).
- **Hybrid grouping** (decided): IDE-launch scenarios grouped by IDE; every other Workbench
  test grouped by feature module.
- **Cross-worker login lock** (decided) to serialize just the SSO round-trip, so concurrent
  workers never hit the shared IdP session at the same time.

**Constraints / decisions:**
- **Single shared account only** — no account pool. (Ruled out provisioning N IdP accounts.)
- Stay close to the current pattern; minimal change (per repo conventions).

**Out (deferred):**
- Baking an established Workbench session into the shared `storage_state` to skip the
  per-test round-trip entirely (the "bake session" option). Faster, but all workers would
  share one Workbench session cookie concurrently. Revisit only if login serialization
  proves to be a wall-clock bottleneck.
- Provisioning multiple test accounts / account-pool auth.

## Mechanism

Both changes live in `src/vip_tests/workbench/conftest.py` and activate **only** when
`config.stash.get(_auth_session_key)` is set — the exact gate the current serial override
uses (`conftest.py:52`). Password / no-auth runs keep today's default behavior untouched.

### Component 1 — Hybrid xdist grouping

Replace the single `workbench_interactive_serial` group assignment with a per-item group:

- **IDE-launch scenarios** → `workbench_ide_<ide>` where `<ide>` ∈
  `rstudio` / `vscode` / `jupyter` / `positron`. IDE type is a **scenario-level** attribute
  (the four scenarios all live in `test_ide_launch.feature`), so the signal is an IDE
  **tag** added to each scenario in the feature file (`@rstudio`, `@vscode`, `@jupyter`,
  `@positron`), which pytest-bdd surfaces as a marker the conftest can read.
- **Every other Workbench test** → `workbench_<module>` (feature-file stem, e.g.
  `workbench_packages`, `workbench_git_ops`, `workbench_sessions`).

xdist LoadGroupScheduling then distributes these groups across workers (bounded by `-n`),
replacing the 1-worker pin. Group count is the *ceiling* on Workbench parallelism; actual
parallelism is bounded by the `-n` worker count.

Rationale for hybrid: "group by IDE type" (the issue's literal ask) is only meaningful for
the IDE-launch scenarios; the rest of the suite isn't IDE-specific. Feature-module grouping
maps cleanly onto the existing collection units for those. Hybrid keeps faithful IDE
splitting where it matters without inventing an IDE tag for every non-IDE test.

### Component 2 — Cross-worker login lock

Wrap **only** the SSO round-trip critical section in `workbench_login`
(`sso_button.click()` → wait for homepage, `conftest.py:391-411`) in a
`filelock.FileLock`, keyed to the Workbench URL, so concurrent workers serialize their
IdP round-trips. Directly removes the root cause (concurrency), not a symptom.

- The already-logged-in **fast path** (`conftest.py:363`) and the **password** login path
  never acquire the lock.
- Lock acquisition uses a **timeout**; on timeout, log a warning and proceed rather than
  hang the run (idempotent-redundancy: the lock is an optimization, never a correctness
  dependency).
- The slow work — session launch and the ~90s `wait_for_session_active` waits — stays
  **outside** the lock and runs in parallel across workers.

### Data flow

```
collection → hybrid group markers assigned (gated on shared auth session)
           → xdist LoadGroupScheduling distributes groups across -n workers
           → per test: SSO round-trip serialized by the file lock (fast path skips it)
                       session launch + IDE interaction run in parallel
```

## Dependency

`filelock` is **not** currently a VIP dependency (confirmed: `import filelock` fails in the
synced env). Add it to `pyproject.toml`. The runtime dependency audit in `ci.yml` must stay
green, so it goes in the runtime deps, not a dev-only group.

## Testing

- **Selftests (pytester, mirrors `selftests/test_plugin.py`):**
  - IDE-launch scenarios get `workbench_ide_<ide>` groups.
  - Non-IDE Workbench tests get `workbench_<module>` groups.
  - The gate still no-ops (no regrouping) under password / no-auth runs.
- **Unit test** around a small lock-wrap helper: acquires and releases, and proceeds on
  timeout without raising.
- **Live behavior cannot run in CI** (needs a real OIDC Workbench). See the spike.

## The one real risk — spike first

The premise that a **single shared account** can sustain 2–4 concurrent Workbench sessions,
and that the login lock actually eliminates the `?error=2` storm, must be **proven against a
live OIDC Workbench 2026.06 deployment** before trusting the rollout. Make this spike the
**first implementation step**. If it fails, fall back (e.g. cap concurrency to 2, or revisit
the deferred "bake session" option).

Secondary consideration (not auth): many concurrent session launches stress the deployment's
launcher. The `-n` worker count naturally bounds this; document it, don't engineer for it.
