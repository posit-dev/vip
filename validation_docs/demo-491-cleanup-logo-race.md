# Fix #491: cleanup sweep waits for homepage logo (SPA hydration race)

*2026-07-17T04:02:42Z by Showboat 0.6.1*
<!-- showboat-id: e8b349b8-76a1-45db-bd1a-981ee1125620 -->

The orphaned-session cleanup sweep (vip cleanup --workbench-url and the in-test teardown) was quitting 0 sessions even with valid auth and sessions clearly present. Root cause: _complete_sso_if_needed detected the authenticated homepage with a one-shot logo.is_visible(). The 2026.05+ dashboard is a shadcn SPA that mounts the #posit-logo ~3s after the page 'load' event, so the snapshot raced hydration, returned False, and the sweep aborted with a misleading 'could not reach an authenticated homepage / may have expired' warning. Fix: a bounded logo.wait_for(state='visible', timeout=TIMEOUT_QUICK), mirroring the SSO-button wait already in the same function and _wait_for_session_list's existing SPA-timing guard.

The fix: one-shot is_visible() replaced by a bounded wait_for on the homepage logo.

```bash
grep -n "logo.wait_for(state=\"visible\", timeout=TIMEOUT_QUICK)" src/vip/workbench_ui.py
```

```output
111:            logo.wait_for(state="visible", timeout=TIMEOUT_QUICK)
```

New regression test reproduces the race (logo missed by a snapshot is_visible() but caught by a bounded wait_for) — it fails on the old code and passes on the fix:

```bash
env -u UV_PROJECT uv run --frozen --no-sync --project . pytest "selftests/test_workbench_cleanup.py::test_complete_sso_true_when_logo_mounts_after_load" -q 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
```

```output
1 passed
```

Full workbench-cleanup selftest module stays green:

```bash
env -u UV_PROJECT uv run --frozen --no-sync --project . pytest selftests/test_workbench_cleanup.py -q 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
```

```output
49 passed
```

Lint clean:

```bash
env -u UV_PROJECT uv run --frozen --no-sync --project . ruff check src/vip/workbench_ui.py selftests/test_workbench_cleanup.py
```

```output
All checks passed!
```

Live validation (dev.demo.posit.team, not re-runnable here — requires a live deployment + browser auth): with 6 orphaned VIP sessions Active, vip cleanup --workbench-url https://dev.demo.posit.team reported 'quit 6 VIP session(s) (10 row(s) visible)' / 'Quit 6 VIP Workbench session(s) via the UI'. Before this fix the same command quit 0 despite the sessions being present and auth valid.
