# Fix: reload page before polling for Active on resume

*2026-05-12T18:02:59Z by Showboat 0.6.1*
<!-- showboat-id: fef45b21-a767-4ac9-bc98-936b0adaf83c -->

Issue #238: `test_session_suspend_resume` consistently timed out at 90 seconds waiting for the Active badge to reappear after resume. Root cause: `page.go_back()` in the resume step leaves a stale homepage DOM where the badge still reads "Suspended", so DOM polling never sees the transition to Active. The fix adds `page.reload(timeout=TIMEOUT_PAGE_LOAD)` plus a homepage-logo wait at the start of the `session_becomes_active_again` step in `src/vip_tests/workbench/test_sessions.py`. End-to-end verification requires a real Workbench deployment, so this demo proves the change is well-formed: the test still collects, lint passes, and the diff is small and reviewable.

```bash
uv run pytest src/vip_tests/ --collect-only --quiet 2>&1 | tail -1 | sed 's/ in [0-9.]*s//'
```

```output
7/103 tests collected (96 deselected)
```

```bash
uv run ruff check src/vip_tests/workbench/test_sessions.py
```

```output
All checks passed!
```

```bash
uv run ruff format --check src/vip_tests/workbench/test_sessions.py
```

```output
1 file already formatted
```

```bash
git diff --stat origin/main -- src/vip_tests/workbench/test_sessions.py
```

```output
 src/vip_tests/workbench/test_sessions.py | 9 +++++++++
 1 file changed, 9 insertions(+)
```

```bash
git diff origin/main -- src/vip_tests/workbench/test_sessions.py
```

```output
diff --git a/src/vip_tests/workbench/test_sessions.py b/src/vip_tests/workbench/test_sessions.py
index d8d067b..5f047d9 100644
--- a/src/vip_tests/workbench/test_sessions.py
+++ b/src/vip_tests/workbench/test_sessions.py
@@ -161,6 +161,15 @@ def session_becomes_active_again(page: Page, session_context: dict):
     """Verify the session transitions back to Active state."""
     session_name = session_context["name"]
 
+    # Reload so the DOM reflects the current server state — go_back() can leave
+    # a cached page where the "Suspended" badge has not been re-rendered.
+    # After the reload, the Workbench homepage's client-side state polling
+    # surfaces the Suspended → Active transition (same pattern used at line
+    # ~128 above, where Playwright's locator polling observes the
+    # Active → Suspended transition without a reload).
+    page.reload(timeout=TIMEOUT_PAGE_LOAD)
+    expect(page.locator(Homepage.POSIT_LOGO)).to_be_visible(timeout=TIMEOUT_PAGE_LOAD)
+
     session_active = page.locator(Homepage.session_row_status(session_name, "Active"))
     try:
         expect(session_active).to_be_visible(timeout=TIMEOUT_SESSION_START)
```

End-to-end verification — confirming the session badge transitions correctly after resume — requires a real Workbench deployment and is tracked for validation against the staging cluster.
