# Implement: #308 — Workbench sign-out scenario

## What was implemented

Added BDD test coverage for the Workbench sign-out flow (Gap 1 of the
three coverage gaps identified in issue #308).

### Changes

- `src/vip_tests/workbench/test_auth.feature` — added "User can sign out
  of Workbench" scenario using the shared `Given Workbench is accessible
  and I am logged in` step already defined in conftest.py
- `src/vip_tests/workbench/test_auth.py` — added `test_workbench_signout`
  scenario binding plus two new step definitions:
  - `When I sign out of Workbench` — tries `#signOutBtn` (legacy) first,
    falls back to submitting `form[action*='sign-out']` (newer Workbench)
  - `Then I am redirected to the Workbench login page` — asserts the login
    form is visible after sign-out, confirming session invalidation
  - Imports: added `TIMEOUT_PAGE_LOAD` and `LoginPage` which the new steps
    require

### Note

The `uv`/`uvx` toolchain was not available in this runner environment, so the
`showboat` demo workflow could not be executed. CI will verify lint and
dry-run scenario collection.
