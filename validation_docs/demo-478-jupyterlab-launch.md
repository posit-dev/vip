# Fix #478: JupyterLab launch/exec resilient to SPA timing

*2026-07-17T17:21:08Z by Showboat 0.6.1*
<!-- showboat-id: f3496fab-2065-48ce-966f-7c87c1d8b98e -->

test_launch_jupyter and test_jupyterlab_extensions skipped with a false 'IDE may not be installed' because they gated on .jp-Launcher, which only exists while the Launcher tab is open -- some deployments open JupyterLab with no Launcher tab. Root causes found by live diagnosis on dev.demo: (1) gate on the wrong element; (2) the #jupyterlab-splash overlay lingers after the shell mounts and intercepts clicks; (3) no Launcher auto-opens; (4) a modal 'Select Kernel' dialog appears a moment after the notebook opens.

Fix: gate readiness on the JupyterLab app shell (.jp-LabShell), present on every load; then in code-exec, wait out the splash, open a Launcher via launcher:create, target the visible notebook, and poll-dismiss the kernel dialog.

```bash
grep -n "SHELL = \|SPLASH = \|LAUNCHER_CREATE_COMMAND = \|DIALOG = " src/vip_tests/workbench/pages/jupyterlab_session.py
```

```output
17:    SHELL = ".jp-LabShell"
21:    SPLASH = "#jupyterlab-splash"
26:    DIALOG = ".jp-Dialog"
55:    LAUNCHER_CREATE_COMMAND = '[data-command="launcher:create"]:visible'
```

The readiness gate now uses the app shell, not the Launcher tab:

```bash
grep -n "JupyterLabSession.SHELL" src/vip_tests/workbench/test_ide_launch.py src/vip_tests/workbench/test_ide_extensions.py
```

```output
src/vip_tests/workbench/test_ide_launch.py:306:    _expect_ide_or_skip(page, JupyterLabSession.SHELL, "JupyterLab")
src/vip_tests/workbench/test_ide_extensions.py:236:    _expect_ide_or_skip(page, JupyterLabSession.SHELL, "JupyterLab")
```

Lint clean:

```bash
env -u UV_PROJECT uv run --frozen --no-sync --project . ruff check src/vip_tests/workbench/test_ide_launch.py src/vip_tests/workbench/test_ide_extensions.py src/vip_tests/workbench/pages/jupyterlab_session.py
```

```output
All checks passed!
```

Live validation on dev.demo.posit.team (not re-runnable here -- needs a live deployment + browser auth): with JupyterLab installed but no auto-opened Launcher, both JupyterLab tests now PASS end-to-end -- test_jupyterlab_extensions PASSED (was skipping with false 'not installed') and test_launch_jupyter PASSED (opens a Launcher, creates a notebook, dismisses the Select-Kernel dialog, runs 1+1, asserts 2). Before this change both skipped claiming JupyterLab may not be installed.
