# Fix: use type() + select-all clear instead of fill() for the RStudio Ace console input

*2026-06-24T14:55:45Z by Showboat 0.6.1*
<!-- showboat-id: 3581df17-eee8-440c-a490-c616753e03c8 -->

The RStudio console input (#rstudio_console_input) is an Ace editor <div>, not a real <input>/<textarea>/[contenteditable]. Playwright's Locator.fill() requires a directly-fillable element, so it raised "Element is not an <input>..." every time test_background_job / test_workbench_job reached it against a loaded RStudio IDE. The fix focuses the editor with click(), clears any leftover text with select-all + delete (Control+a, Backspace), then type()s real keystrokes into the focused hidden Ace textarea — the established idiom in test_packages.py. The identical latent bug in test_data_sources.py (fill("") on the same div, in a per-data-source loop) is fixed the same way.

```bash
git diff main..HEAD -- src/vip_tests/workbench/test_jobs.py src/vip_tests/workbench/test_data_sources.py
```

```output
diff --git a/src/vip_tests/workbench/test_data_sources.py b/src/vip_tests/workbench/test_data_sources.py
index 049551c..8745a75 100644
--- a/src/vip_tests/workbench/test_data_sources.py
+++ b/src/vip_tests/workbench/test_data_sources.py
@@ -92,8 +92,14 @@ def _execute_r_command(page: Page, command: str) -> str:
     console_input = page.locator(ConsolePaneSelectors.INPUT)
     expect(console_input).to_be_visible(timeout=_TIMEOUT_CONSOLE_READY)
 
+    # The console input is an Ace editor <div>, not a real <input>/<textarea>,
+    # so Locator.fill() raises "Element is not an <input>...". Select-all +
+    # delete to clear any leftover text (this helper runs once per data source
+    # in a loop), then type real keystrokes into the focused hidden Ace textarea
+    # (matches test_packages.py).
     console_input.click()
-    console_input.fill("")
+    page.keyboard.press("Control+a")
+    page.keyboard.press("Backspace")
     console_input.type(command)
     console_input.press("Enter")
 
diff --git a/src/vip_tests/workbench/test_jobs.py b/src/vip_tests/workbench/test_jobs.py
index 1d1e7b8..ad9dc57 100644
--- a/src/vip_tests/workbench/test_jobs.py
+++ b/src/vip_tests/workbench/test_jobs.py
@@ -198,7 +198,13 @@ def write_test_script(page: Page):
     # Build the writeLines() call as a single-line R expression.
     escaped = _JOB_SCRIPT_CONTENT.replace('"', '\\"')
     r_cmd = f'writeLines("{escaped}", "{_JOB_SCRIPT_FILENAME}")'
-    console_input.fill(r_cmd)
+    # The console input is an Ace editor <div>, not a real <input>/<textarea>,
+    # so Locator.fill() raises "Element is not an <input>...". Select-all +
+    # delete to clear any leftover text, then type real keystrokes into the
+    # focused hidden Ace textarea (matches test_packages.py).
+    page.keyboard.press("Control+a")
+    page.keyboard.press("Backspace")
+    console_input.type(r_cmd)
     console_input.press("Enter")
 
     # Wait for the prompt to return (console is ready for next command).
```

```bash
uv run ruff check src/vip_tests/workbench/test_jobs.py src/vip_tests/workbench/test_data_sources.py
```

```output
All checks passed!
```

```bash
uv run ruff format --check src/vip_tests/workbench/test_jobs.py src/vip_tests/workbench/test_data_sources.py
```

```output
2 files already formatted
```

```bash
uv run pytest --collect-only src/vip_tests/workbench/test_jobs.py src/vip_tests/workbench/test_data_sources.py -q -p no:cacheprovider 2>&1 | grep -E "deselected|error|collected" | sed "s/ in [0-9.]*s//"
```

```output
no tests collected (3 deselected)
```
