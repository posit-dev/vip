# Fix: Workbench orphaned-session cleanup escalation (issue #467)

*2026-07-15T18:41:14Z by Showboat 0.6.1*
<!-- showboat-id: 0915325c-b729-41d8-89ae-3e21e6b99e2d -->

Issue #467: VIP's Workbench product tests left orphaned sessions behind
(named "VIP <file> - <worker>-<ns>" and "_vip_cap_<ts>_..."). Root cause: three
layers each trusted a signal that didn't actually confirm cleanup.

1. `WorkbenchClient.quit_session` treated any HTTP status below 400 as success
   without verifying the session actually terminated -- a deployment whose
   DELETE/suspend is a silent no-op looked "successful."
2. The per-test `_cleanup_sessions` fixture only escalated to a browser-driven
   UI sweep when the session API was *unreachable*. When the API was reachable
   but its DELETE was a no-op, sessions persisted and the UI fallback never
   fired -- the exact #467 leak.
3. Every layer swallowed exceptions silently, so the issue report had empty logs.
4. `vip cleanup` only cleaned Connect content; there was no out-of-band recovery
   for orphaned Workbench sessions if `vip verify` crashed mid-run.

This demo proves the fix for all four:
- `WorkbenchClient.quit_vip_sessions` now logs a WARNING (not silence) when a
  VIP session is still listed after exhausting its retries.
- The per-test cleanup fixture (`_run_session_cleanup`, extracted from
  `_cleanup_sessions` for testability) now escalates to the UI sweep whenever
  the API is unreachable *or* VIP sessions remain after the API sweep --
  not only when the API is unreachable.
- `vip cleanup --workbench-url` is a new browser-driven escape hatch: it
  authenticates (reusing a `vip verify` auth cache when available), sweeps
  via the session API, and escalates to the same UI sweep used by the test
  fixture.
- The UI sweep itself (`quit_vip_sessions_via_ui`) moved to `src/vip/workbench_ui.py`
  so both the pytest fixture and the standalone CLI command share one
  implementation instead of drifting apart.

New selftests covering Change A (loud warning on a stuck session) all pass:

```bash
uv run pytest selftests/test_workbench_cleanup.py -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
35 passed
```

New selftests covering Change B (per-test cleanup fixture escalation logic in _run_session_cleanup) and Change C (authenticated_page, vip cleanup CLI wiring) all pass:

```bash
uv run pytest selftests/test_auth.py selftests/test_cli_cleanup.py -q 2>&1 | grep -E '^[0-9]+ (passed|failed)' | sed 's/ in [0-9.]*s//'
```

```output
96 passed, 4 warnings
```

The new --workbench-url flag on vip cleanup:

```bash
uv run vip cleanup --help
```

```output
usage: vip cleanup [-h] [--connect-url CONNECT_URL] [--api-key API_KEY]
                   [--workbench-url WORKBENCH_URL]

Delete VIP _vip_test-tagged content from Connect, and/or quit orphaned
VIP-named Workbench sessions. At least one of --connect-url /
--workbench-url (or the corresponding vip.toml URL) must resolve.

  vip cleanup --connect-url https://connect.example.com
  vip cleanup --workbench-url https://workbench.example.com

options:
  -h, --help            show this help message and exit
  --connect-url CONNECT_URL
                        Connect server URL (falls back to vip.toml if omitted)
  --api-key API_KEY     Connect API key (default: VIP_CONNECT_API_KEY env var)
  --workbench-url WORKBENCH_URL
                        Workbench server URL (falls back to vip.toml if
                        omitted). Quits orphaned VIP-named sessions via the
                        session API, escalating to a browser-driven UI sweep
                        if the API is unreachable or sessions persist.
                        Requires VIP_TEST_USERNAME/VIP_TEST_PASSWORD for non-
                        interactive auth, or an interactive browser login.
```

Lint, format, and type checks (just check covers ruff lint + format; mypy run separately):

```bash
just check
```

```output
uv run ruff check src/ selftests/ examples/ docker/
All checks passed!
uv run ruff format --check src/ selftests/ examples/ docker/
159 files already formatted
```

Type checking (mypy, run in CI as a separate job):

```bash
uv run mypy src/vip/
```

```output
src/vip/load_users.py:124: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
src/vip/load_users.py:125: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 29 source files
```

Full selftest suite (excluding selftests/test_load_engine.py, which has 2 known timing-flaky tests unrelated to this change -- see CLAUDE.md):

```bash
uv run pytest selftests/ --ignore=selftests/test_load_engine.py -q 2>&1 | grep -E '^[0-9]+ (passed|failed)' | sed 's/ in [0-9.]*s//'
```

```output
922 passed, 26 warnings
```
