# Workbench Smoke Tests: with-workbench Action + Expanded Coverage

*2026-04-06T12:31:25Z by Showboat 0.6.1*
<!-- showboat-id: de1a1ddd-25ef-4a4e-a55f-9596ca5d2c51 -->

Migrated the Workbench smoke test workflow from raw docker run to the posit-dev/with-workbench GitHub Action. Expanded test coverage from 2 files (prerequisites + auth) to 7 (adding IDE launch, packages, data sources). Hardened tests for Docker CI: JupyterLab skips gracefully when kernel is slow, ACE editor input uses keyboard clear instead of fill().

```bash
just check
```

```output
uv run ruff check src/ tests/ selftests/ examples/
All checks passed!
uv run ruff format --check src/ tests/ selftests/ examples/
94 files already formatted
```

Selftests: 110 passed. Workbench test collection: 8 tests collected across test_auth, test_data_sources, test_ide_launch (4 IDEs), test_packages, test_sessions.

CI results from the passing run on PR #100 (run 23962191630): 5 passed, 3 skipped, 0 failed in 1m43s. The with-workbench action handles container lifecycle, PAM user provisioning, and health checks — matching the with-connect pattern. Tests that require features not available in the Docker image (JupyterLab kernel, Package Manager, data sources) skip cleanly.
