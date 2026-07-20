# feat(workbench): parallelize BDD suite under shared auth (#484)

*2026-07-20T23:23:12Z by Showboat 0.6.1*
<!-- showboat-id: 6d8bd6b9-7c0f-407d-b5c5-00496e9b7472 -->

Before: under --interactive-auth / --headless-auth every Workbench test (auth, IDE launch, sessions, packages) was pinned to a single xdist worker via the workbench_interactive_serial group -- avoiding a shared-IdP login storm at the cost of ~10 min of forced serial execution. After: two changes replace that pin. (1) A cross-worker filelock (oidc_login_lock, keyed by a hash of the Workbench URL) now serializes ONLY the OIDC silent-sign-in round-trip in _silent_sso_signin/workbench_login -- the part that actually storms the IdP -- so it can time out and proceed unlocked rather than hang the run. (2) pytest_collection_modifyitems in src/vip_tests/workbench/conftest.py replaces the single-worker pin with hybrid xdist grouping via _workbench_group_name: IDE-launch scenarios group by IDE (workbench_ide_rstudio/vscode/jupyter/positron) so each IDE gets its own worker, and every other Workbench test groups by feature module (workbench_<stem>, e.g. workbench_packages, workbench_git_ops). This only fires when a shared auth session is active (config.stash has an auth session); password/no-auth runs are untouched. Net effect: Workbench tests now spread across multiple xdist workers instead of funneling through one, while the login-lock keeps the shared IdP from being hammered by concurrent sign-ins.

```bash
uv run pytest selftests/test_workbench_parallel.py -q 2>&1 | grep -E "passed|failed|error" | sed 's/ in [0-9.]*s//'
```

```output
12 passed
```

```bash
uv run pytest selftests/ --ignore=selftests/test_load_engine.py -q 2>&1 | grep -E "passed|failed|error" | sed 's/ in [0-9.]*s//'
```

```output
1029 passed, 22 warnings
```

```bash
just check
```

```output
uv run ruff check src/ selftests/ examples/ docker/
All checks passed!
uv run ruff format --check src/ selftests/ examples/ docker/
164 files already formatted
```

```bash
uv run python -c "from vip_tests.workbench.conftest import _workbench_group_name as g; print(g({'rstudio'},'test_ide_launch')); print(g({'positron'},'test_ide_launch')); print(g(set(),'test_packages')); print(g(set(),'test_git_ops'))"
```

```output
workbench_ide_rstudio
workbench_ide_positron
workbench_packages
workbench_git_ops
```
