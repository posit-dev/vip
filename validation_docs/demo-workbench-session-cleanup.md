# Fix: reliable Workbench session cleanup (#277)

*2026-05-29T18:53:34Z by Showboat 0.6.1*
<!-- showboat-id: 8db398fc-5077-4456-b28c-ce839a3b2f33 -->

Issue #277: when a Workbench test failed mid-IDE, the session it launched was left running on the homepage, forcing users to quit orphans by hand. Cleanup is now centralized in WorkbenchClient.quit_vip_sessions(), which lists sessions and force-quits only VIP-named ones (the 'VIP ' and '_vip_' prefixes), then re-lists to verify they are gone and retries. It is resilient to malformed API payloads (non-JSON bodies, null/non-string labels) and counts unique sessions. A session-scoped end-of-run sweep is a safety net so a single failed per-test cleanup no longer orphans a session, with an API-key fallback for long runs where browser cookies may have expired. Cleanup authenticates with the browser's cookies, so no API key is required.

```bash
uv run pytest selftests/test_workbench_cleanup.py -n0 -q 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
```

```output
15 passed
```

```bash
uvx ruff@0.15.0 check src/ selftests/ examples/ docker/
```

```output
All checks passed!
```

```bash
uvx ruff@0.15.0 format --check src/ selftests/ examples/ docker/
```

```output
133 files already formatted
```

```bash
uv run pytest src/vip_tests/workbench/ --collect-only -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
no tests collected (12 deselected)
```
