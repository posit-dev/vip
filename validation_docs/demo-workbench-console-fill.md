# Fix: use type() instead of fill() for the RStudio Ace console input

*2026-06-24T14:38:42Z by Showboat 0.6.1*
<!-- showboat-id: 2ab8faa5-2c73-4c5b-b1cb-c9d3c2a9fe21 -->

The RStudio console input (#rstudio_console_input) is an Ace editor <div>, not a real <input>/<textarea>/[contenteditable]. Playwright's Locator.fill() requires a directly-fillable element, so it raised "Element is not an <input>..." every time test_background_job / test_workbench_job reached it against a loaded RStudio IDE. The fix switches to click()+type(), which sends real keystrokes to the focused hidden Ace textarea — the canonical pattern already used in exec.py, test_packages.py, and test_runtime_versions.py. The identical latent bug in test_data_sources.py (fill("") on the same div) is fixed too.

```bash
git diff main..HEAD -- src/vip_tests/workbench/test_jobs.py src/vip_tests/workbench/test_data_sources.py
```

```output
diff --git a/src/vip_tests/workbench/test_data_sources.py b/src/vip_tests/workbench/test_data_sources.py
index 049551c..75039fe 100644
--- a/src/vip_tests/workbench/test_data_sources.py
+++ b/src/vip_tests/workbench/test_data_sources.py
@@ -92,8 +92,11 @@ def _execute_r_command(page: Page, command: str) -> str:
     console_input = page.locator(ConsolePaneSelectors.INPUT)
     expect(console_input).to_be_visible(timeout=_TIMEOUT_CONSOLE_READY)
 
+    # The console input is an Ace editor <div>, not a real <input>/<textarea>,
+    # so Locator.fill() raises "Element is not an <input>...". click() focuses
+    # the editor (empty at a fresh prompt) and type() sends real keystrokes to
+    # the hidden Ace textarea (matches the canonical pattern in exec.py).
     console_input.click()
-    console_input.fill("")
     console_input.type(command)
     console_input.press("Enter")
 
diff --git a/src/vip_tests/workbench/test_jobs.py b/src/vip_tests/workbench/test_jobs.py
index 1d1e7b8..e322bb0 100644
--- a/src/vip_tests/workbench/test_jobs.py
+++ b/src/vip_tests/workbench/test_jobs.py
@@ -198,7 +198,10 @@ def write_test_script(page: Page):
     # Build the writeLines() call as a single-line R expression.
     escaped = _JOB_SCRIPT_CONTENT.replace('"', '\\"')
     r_cmd = f'writeLines("{escaped}", "{_JOB_SCRIPT_FILENAME}")'
-    console_input.fill(r_cmd)
+    # The console input is an Ace editor <div>, not a real <input>/<textarea>,
+    # so Locator.fill() raises "Element is not an <input>...". Use type() to
+    # send real keystrokes to the focused hidden Ace textarea (see exec.py).
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
