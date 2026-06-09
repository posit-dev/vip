# Fix: reliable Connect content cleanup

*2026-05-29T20:29:44Z by Showboat 0.6.1*
<!-- showboat-id: 43e48303-245d-438b-b3d1-8ee7834500de -->

Connect deploy tests previously left content on the server when a test failed before its cleanup step (the cleanup was a Gherkin @then step, skipped on failure, with no backstop). Cleanup now lives in ConnectClient.cleanup_content() — an idempotent verified delete (404=gone) with retry, always attempting at least one delete. Created content GUIDs are tracked in a session-scoped list and deleted by an autouse per-test finalizer that runs on pass or fail, plus a session-scoped end-of-run sweep that also runs the tag-based cross-run cleanup_vip_content(). Package Manager was audited and needs no fix (its tests are read-only).

```bash
uv run pytest selftests/test_connect_cleanup.py -n0 -q 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
```

```output
8 passed
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
uv run pytest src/vip_tests/connect/ --collect-only -q 2>&1 | tail -1 | sed "s/ in [0-9.]*s//"
```

```output
1/22 tests collected (21 deselected)
```
