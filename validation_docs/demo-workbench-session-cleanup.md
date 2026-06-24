# Feature: Workbench session-cleanup robustness + macOS console clear

*2026-06-24T18:39:25Z by Showboat 0.6.1*
<!-- showboat-id: 5fa1c913-d846-4abb-a9ff-2c6b79d76f99 -->

This branch bundles four Workbench-test robustness fixes:

1. ControlOrMeta+a (not Control+a) to clear the Ace console input, so the select-all clear works on macOS (where Ctrl+A is 'go to line start'). Applied to test_data_sources, test_jobs, test_packages.
2. Fail fast with an actionable message when a session reaches terminal 'Failed' during suspend, instead of an opaque 30s timeout (test_sessions).
3. Same fail-fast in the idle auto-suspend reload loop (test_session_idle), via shared raise_if_session_failed/_visible_terminal_state.
4. UI-based fallback session cleanup: a sessions_api_reachable() probe, a VIP-name filter, and a homepage UI sweep wired into _cleanup_sessions (gated on reachability, cached once per session) so orphaned VIP sessions are quit on deployments whose /api/sessions 404s.

Unit-testable pieces are covered by the selftests below. Browser-driven behavior (console clears, suspend/resume, the UI sweep click-through) is verified against a live Workbench; the suspend/resume scenario was confirmed PASS against workbench.posit.it.

```bash
uv run pytest selftests/test_workbench_cleanup.py selftests/test_workbench_session_active.py -q 2>&1 | grep -E "passed|failed" | sed 's/ in [0-9.]*s//'

```

```output
37 passed
```

```bash
just check

```

```output
uv run ruff check src/ selftests/ examples/ docker/
All checks passed!
uv run ruff format --check src/ selftests/ examples/ docker/
160 files already formatted
```
