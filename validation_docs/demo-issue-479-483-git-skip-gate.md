# Fix: workbench git-ops skip reasons + default public clone repo

*2026-07-16T19:23:40Z by Showboat 0.6.1*
<!-- showboat-id: b188b399-5b35-4006-9996-37481c8f6963 -->

This branch fixes two related Workbench git-ops bugs.

**#479 — misleading auth skip when git config is absent.** Every scenario in test_git_ops.feature checked the auth-session login gate BEFORE the git-config gate. Because Workbench OIDC auth is flaky under the shared-account serial run, whether a git test skipped with the config reason or the auth reason was non-deterministic — push tests could report a misleading 'Workbench session not established' error when the real reason was 'no git config / read-only'. Fixed by reordering the Gherkin steps so the config gate (and, for push scenarios, the pushing gate) resolves before the login attempt.

**#483 — public-repo cloning wrongly appeared to require VIP_GIT_TOKEN.** There was no default [workbench.git_test] config, so clone scenarios always skipped without one, and the skip message read as if a token was required even for anonymous public clones. Fixed by shipping a default public clone target (`https://github.com/posit-dev/posit-cli.git`, auth_method="none") that WorkbenchConfig.from_dict synthesizes when the block is absent, and by rewording the skip messages to make clear a token is only needed for push/private-repo scenarios.

### Fix #479: config gate now precedes login in every scenario

Before this fix, step 1 was the login attempt and step 2 was the config check. Now the config check runs first:

```bash
grep -n -A4 "Scenario: Clone a Git repository in RStudio" src/vip_tests/workbench/test_git_ops.feature
```

```output
11:  Scenario: Clone a Git repository in RStudio terminal
12-    Given the Git test config is available
13-    And Workbench is accessible and I am logged in
14-    When I launch an RStudio session
15-    And I clone the repository in the RStudio terminal
```

### Fix #483: reworded skip message makes clear public clones need no token

The config-missing skip message now explicitly says an anonymous public-repo clone needs only `clone_url` + `auth_method='none'` (no token), and a token is only required for push/private-repo scenarios:

```bash
sed -n "219,225p" src/vip_tests/workbench/test_git_ops.py
```

```output
        pytest.skip(
            "Git test config is not configured. "
            "Cloning a public repo needs only clone_url and auth_method='none' "
            "in a [workbench.git_test] block of vip.toml (no token required). "
            "Push/private-repo scenarios additionally need auth_method='https-token' "
            "with VIP_GIT_TOKEN set in the environment."
        )
```

### New selftests pass: default-config synthesis, step-order guard, skip-message wording

```bash
env -u UV_PROJECT uv run --frozen --no-sync --project . pytest selftests/test_config.py selftests/test_workbench_git_ops.py -q 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
```

```output
111 passed, 1 warning
```

### Full selftest suite is green (excluding `selftests/test_load_engine.py`, which has pre-existing timing-flaky tests unrelated to this change; run with `-n0` since the repo's default `-n auto` xdist parallelism is itself intermittently flaky, unrelated to this change)

```bash
UV_FROZEN=1 env -u UV_PROJECT uv run --frozen --no-sync --project . pytest selftests/ -q --ignore=selftests/test_load_engine.py -n0 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
```

```output
950 passed, 11 warnings
```

### Lint and format check (`just check` equivalent — run directly with the project-scoped uv wrapper since `just`'s recipes invoke bare `uv`, which reroots to the parent ptd-workspace in this environment)

```bash
env -u UV_PROJECT uv run --frozen --no-sync --project . ruff check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

```bash
env -u UV_PROJECT uv run --frozen --no-sync --project . ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
159 files already formatted
```

### The 6 git-ops scenarios still collect after the feature-file reorder

Workbench product tests deselect entirely without a configured URL, so this confirms collection with a minimal `[workbench]` config:

```bash
printf "[workbench]\nurl = \"https://workbench.example.com\"\n" > "$TMPDIR/vip_demo.toml" && env -u UV_PROJECT uv run --frozen --no-sync --project . pytest --collect-only -q --vip-config "$TMPDIR/vip_demo.toml" src/vip_tests/workbench/test_git_ops.py 2>/dev/null | sed "s/ in [0-9.]*s//"; rm -f "$TMPDIR/vip_demo.toml"
```

```output
src/vip_tests/workbench/test_git_ops.py::test_clone_rstudio[chromium]
src/vip_tests/workbench/test_git_ops.py::test_push_rstudio[chromium]
src/vip_tests/workbench/test_git_ops.py::test_clone_vscode[chromium]
src/vip_tests/workbench/test_git_ops.py::test_push_vscode[chromium]
src/vip_tests/workbench/test_git_ops.py::test_clone_positron[chromium]
src/vip_tests/workbench/test_git_ops.py::test_push_positron[chromium]

6 tests collected
```

### Follow-up fix: R file-readback quoting bug (surfaced once #483 made clone run by default)

Live validation of #483's default clone against dev.demo.posit.team exposed a third bug: `read_file()`'s R branches evaluated a bare `paste(readLines(...), collapse="\\n")` expression. The R REPL auto-prints that as a quoted, backslash-escaped character vector, which appended a stray `"` to the `terminal_run` done-marker line (`...:0\"`). `_parse_done_marker` then rejected the exit code as non-numeric, so `terminal_run` spun until its 120s timeout even though the underlying command had finished in ~1.5s — this is what made `test_clone_rstudio` time out.

The fix wraps the read in `cat()` via a new `_read_file_r_expr` helper, so R emits raw bytes instead of an auto-printed quoted vector, and drops the now-unnecessary `_strip_r_index` call on those reads (both the RStudio and Positron R-console readback paths used the same buggy expression).

```bash
env -u UV_PROJECT uv run --frozen --no-sync --project . pytest "selftests/test_workbench_exec.py::TestReadFileRExpr" "selftests/test_workbench_exec.py::TestParseDoneMarker::test_raw_exit_code_parses_but_quoted_does_not" -q 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
```

```output
3 passed
```

```bash
grep -n "cat(paste(readLines" src/vip_tests/workbench/exec.py
```

```output
97:    return f'cat(paste(readLines("{path}"), collapse="\\n"))'
```

### Live validation on dev.demo.posit.team

Not re-runnable in this document (requires a live deployment + interactive browser auth), so recorded here as prose instead of an exec block:

Running a config-less `--interactive-auth` pass against dev.demo.posit.team (a real 2026.06-class deployment):
- `test_clone_vscode` **PASSED** — proves the #483 default clone (posit-dev/posit-cli, no config, no token) works end-to-end against a real Workbench instance.
- `test_clone_rstudio` **PASSED in ~23s** — before this readback fix it was hitting the full 120s `terminal_run` timeout; the `cat()` wrap resolved the done-marker parsing failure described above.
- Push scenarios **skipped** with the accurate read-only reason (`auth_method='none' is anonymous (read-only)...`), confirming the #479 reorder surfaces the real skip reason instead of a login-flake error.
- `test_clone_positron` / `test_push_positron` were not exercised — dev.demo has no Positron IDE installed, so the Positron launch gate (#477) remains deferred pending a Positron-enabled deployment.
