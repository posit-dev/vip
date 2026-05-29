# Reliable Connect content cleanup

**Related:** follows the Workbench session-cleanup fix ([#277](https://github.com/posit-dev/vip/issues/277) / PR #312). This applies the same orphan-cleanup pattern to Connect.

## Problem

Connect deploy tests create content items (apps/docs) on the server. When a test
fails mid-scenario, that content is left behind on Connect with no automated
cleanup. The orphan-leak risk is structurally **worse** than Workbench's was.

### Current state

- Cleanup is a Gherkin `@then` step, not a fixture finalizer:
  - `src/vip_tests/connect/test_content_deploy.py:521` — `@then("I clean up the
    test content")` → `connect_client.delete_content(deploy_state["guid"])`.
  - `src/vip_tests/connect/test_packages.py:121` — same pattern.
  In pytest-bdd, a failure in any earlier step stops the scenario, so the
  cleanup step **never runs** on failure → orphaned content.
- `src/vip_tests/connect/conftest.py` has **no** autouse fixture, `yield`
  finalizer, or `addfinalizer` cleanup. There is no backstop.
- The only sweep, `cleanup_vip_content()` (`src/vip/clients/connect.py:202`),
  is invoked solely by the manual `vip cleanup` / `vip uninstall` CLI
  (`cli.py:897`, `cli.py:949`) — never by the test run.
- `cleanup_vip_content()` swallows per-item delete errors silently with no
  retry or verification (`connect.py:209-216`); `list_vip_content()` swallows
  all errors and returns `[]` (`connect.py:189-200`).
- `_tag_content()` is best-effort `except Exception: pass` (`connect.py:225-238`):
  if tagging fails, the content exists but is **untagged** and therefore
  invisible to the tag-based sweep.
- `deploy_state` starts as `{}` (`test_content_deploy.py:81`) but the
  `create_content` step uses `target_fixture` to **return a new dict**
  (`test_content_deploy.py:351`), so a finalizer on the base `deploy_state`
  fixture would never observe the `guid`. Cleanup must track GUIDs explicitly.

### What Connect already gets right

`cleanup_vip_content()` is correctly scoped to the `_vip_test` tag, so it never
deletes non-VIP content. No over-broad-deletion risk.

### Resources created

Only **content items**, all named `vip-<type>-test` and tagged `_vip_test`:
- `test_content_deploy.py:350` — 8 types (quarto, plumber, shiny, dash,
  rmarkdown, jupyter, fastapi, gitbacked).
- `test_packages.py:84` — `vip-pm-repo-test`.

No users, API keys, schedules, variables, or data-source configs are created.

## Decisions

- **Scope:** mirror #277 in full — explicit per-run GUID tracking + an autouse
  per-test finalizer + a session-scoped end-of-run sweep + client hardening.
- **Cross-run:** the end-of-run sweep cleans up **both** this run's tracked
  GUIDs (tag-independent) **and** prior-run orphans via the tag-based
  `cleanup_vip_content()`.
- **Out of scope:** no `vip cleanup` CLI changes (it already calls
  `cleanup_vip_content`, which is hardened here); no Package Manager changes
  (its tests are entirely read-only — audited, no orphan risk).

## Design

### 1. Client hardening — `src/vip/clients/connect.py`

- `_delete_content_verified(guid, *, retries=2, settle_seconds=1.0) -> bool` —
  DELETE the content (treat **404 as already-gone = success**), then GET to
  confirm a 404; retry up to *retries* times if it is still present. Never
  raises. Returns `True` when the content is confirmed gone.
- `cleanup_content(guids, *, retries=2, settle_seconds=1.0) -> int` — the analog
  of `WorkbenchClient.quit_vip_sessions`. Deletes each given GUID via
  `_delete_content_verified`, skipping falsy GUIDs; returns the count confirmed
  deleted. Never raises.
- Rework `cleanup_vip_content()` to delete each tagged item via
  `_delete_content_verified` (verify + retry) instead of the current silent
  single-shot loop. Still returns the count deleted; still never raises.
- Leave `delete_content` (which calls `raise_for_status`) unchanged — the
  happy-path `@then` step and the 409-retry inside `create_content` rely on it
  raising.
- `_tag_content` stays best-effort. It is no longer load-bearing for within-run
  cleanup because GUIDs are now tracked explicitly; it still feeds the
  cross-run tag sweep.

### 2. Test fixtures — `src/vip_tests/connect/conftest.py`

- `_connect_created_guids` (**session-scoped**): returns an append-only `list`
  — the authoritative record of content created this run, independent of tags.
- `_connect_content_cleanup` (**function-scoped, autouse**): records
  `start = len(_connect_created_guids)` at setup, `yield`s, then on teardown
  (pass *or* fail) calls `connect_client.cleanup_content(_connect_created_guids[start:])`,
  deleting exactly the content this test created. No-op when `connect_client`
  is `None` or nothing was created. This is the per-test finalizer that fixes
  the core "cleanup skipped on failure" bug.
- `_connect_end_of_run_sweep` (**session-scoped, autouse**): on teardown, calls
  `connect_client.cleanup_content(_connect_created_guids)` (idempotent backstop
  for anything a per-test finalizer missed) and then
  `connect_client.cleanup_vip_content()` (tag-based, catches prior-run
  orphans). No-op when `connect_client` is `None`.

Under pytest-xdist each worker is a separate process with its own
session-scoped fixtures, so the `[start:]` slice always isolates the current
test's content — no cross-worker contamination.

### 3. Create steps

`create_content` (`test_content_deploy.py:342`) and the packages create step
(`test_packages.py:84`) gain the `_connect_created_guids` fixture and append the
new `guid` immediately after `connect_client.create_content(...)`. The existing
`@then("I clean up …")` steps remain as happy-path assertions; they are now
redundant with the finalizer but harmless because deletes are idempotent.

### 4. Testing — selftests (no real Connect)

New `selftests/test_connect_cleanup.py` using `httpx.MockTransport` on a
`ConnectClient` (mirrors `selftests/test_workbench_cleanup.py`):

- `cleanup_content`: deletes the given GUIDs and returns the count; is
  idempotent when DELETE returns 404; retries a GUID that is still present on
  first verify then succeeds; skips falsy GUIDs; returns 0 and never raises on
  transport errors / non-2xx.
- `_delete_content_verified`: 404-on-DELETE counts as gone; GET-returns-404
  after DELETE confirms gone; GET-still-200 means not gone (retry).
- `cleanup_vip_content` (hardened): lists by tag then deletes via the verified
  path and returns the count; returns 0 and never raises when the tag lookup
  fails.

Handlers match on the request path suffix so the client's `/__api__` prefix
does not need to be hard-coded.

## Verification

- `uv run pytest selftests/ -v` (new + existing pass).
- `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/` and
  `format --check` (CI pins ruff 0.15.0).
- `--collect-only` of `src/vip_tests/connect/` still collects.
- Showboat demo committed under `validation_docs/`, pasted into the PR `## Demo`.
