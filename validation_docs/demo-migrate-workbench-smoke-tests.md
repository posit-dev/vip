# Workbench Smoke Tests: with-workbench Action + Expanded Coverage

*2026-04-06T12:34:28Z by Showboat 0.6.1*
<!-- showboat-id: 379ca146-1449-4de8-8162-fb5fe07fd62b -->

Migrated the Workbench smoke test workflow from raw docker run to the posit-dev/with-workbench GitHub Action. Expanded test coverage from 2 files (prerequisites + auth) to 7 (adding IDE launch, packages, data sources). Hardened tests for Docker CI: JupyterLab skips gracefully when kernel is slow, ACE editor input uses keyboard clear instead of fill().

```bash
uv run ruff check src/ selftests/ examples/
```

```output
All checks passed!
```

```bash
uv run ruff format --check src/ selftests/ examples/
```

```output
94 files already formatted
```

Selftests: 110 passed. Workbench test collection: 8 tests collected across test_auth, test_data_sources, test_ide_launch (4 IDEs), test_packages, test_sessions.

CI results from the passing run on PR #100 (run 23962191630): 5 passed, 3 skipped, 0 failed in 1m43s. The with-workbench action handles container lifecycle, PAM user provisioning, and health checks — matching the with-connect pattern. Tests that require features not available in the Docker image (JupyterLab kernel, Package Manager, data sources) skip cleanly.
