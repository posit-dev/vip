# Plan for issue #307: Publish to Connect from a Workbench session

## Context

VIP's existing `test_content_deploy.feature` validates Connect's publishing pipeline by deploying bundles via the Connect API, but it skips the user-facing workflow most customers exercise during UAT: opening a Workbench session and publishing from within it using tools like `rsconnect-python` or the Posit Publisher extension. A customer's UAT plan specifically requested two scenarios: (1) deploying a Python Shiny app from a VS Code/Positron terminal via `rsconnect-python`, and (2) deploying via the Posit Publisher extension UI. Both prove the chain Workbench → user-facing tool → Connect, which the current API-driven tests don't cover. Additionally, Python Shiny deployment is not currently tested at all (R Shiny is present, Python Shiny is not).

## Architecture

This lands in `src/vip_tests/` as a new cross-product feature file that requires both `@workbench` and `@connect` markers. The test uses existing fixtures (`workbench_client`, `connect_client`) from `src/vip_tests/conftest.py` and builds on the Workbench session management primitives already in place (`test_sessions.py`). The terminal scenario depends on a new in-session command execution capability (tracked separately) that allows running shell commands inside an active Workbench session. The Publisher scenario is Playwright-driven and requires the IDE extension installation primitive (tracked in a separate misc-gaps issue) to ensure the Posit Publisher extension is present before driving it.

## Components

**New files:**
- `src/vip_tests/workbench/test_publish_to_connect.feature` — Gherkin scenarios for terminal-based and UI-based publishing from Workbench to Connect
- `src/vip_tests/workbench/test_publish_to_connect.py` — Step definitions for the new scenarios
- `src/vip_tests/_bundles/python_shiny/app.py` — Minimal Python Shiny test app
- `src/vip_tests/_bundles/python_shiny/requirements.txt` — Dependencies for the Python Shiny bundle
- `validation_docs/demo-bot-plan-issue-307.md` — Showboat demo proving the plan is complete

**Modified files:**
- `src/vip_tests/workbench/conftest.py` — May need session-scoped fixtures for in-session command execution if not already present
- `src/vip_tests/conftest.py` — May need shared fixtures for bundle paths or cleanup utilities

## Verification

```bash
# Dry-run collection to verify the feature is recognized
uv run vip verify --config vip.toml --categories workbench --collect-only | grep "test_publish_to_connect"

# Run against a live Workbench + Connect deployment
uv run vip verify --config vip.toml --categories workbench -- -k publish_to_connect -v
```

Success criteria:
- Both scenarios are collected when `@workbench` and `@connect` products are configured
- Terminal scenario creates a Workbench session, runs `rsconnect-python deploy` inside it, and verifies the app is reachable on Connect
- Publisher scenario opens Positron, uses the extension to deploy, and verifies deployment
- Cleanup step deletes the deployed content item via `connect_client` regardless of which path created it
- Lint passes: `uv run ruff check src/vip_tests/ selftests/`

## Open questions

- **UNCONFIRMED**: Does the in-session command execution primitive already exist, or does this plan depend on implementing it first? If not implemented, the terminal scenario should be marked as skipped with a dependency note until the primitive is available.
- **UNCONFIRMED**: Does the IDE extension installation primitive already exist? If not, the Publisher scenario should similarly be marked as pending that dependency.
- **UNCONFIRMED**: Should the Python Shiny bundle be a reusable fixture (e.g., `python_shiny_bundle_path`) or inlined in the step definitions?

## Out of scope

- Implementing the in-session command execution primitive — tracked separately as a Workbench driver capability gap.
- Implementing the IDE extension installation primitive — tracked separately as a misc-gaps issue.
- Adding R Shiny publishing from Workbench — the issue specifically requests Python Shiny, and R Shiny deployment via Connect API is already covered in `test_content_deploy.feature`.
- Testing deployment failure scenarios (e.g., invalid credentials, missing permissions) — this plan focuses on the happy path to establish the baseline cross-product flow.
