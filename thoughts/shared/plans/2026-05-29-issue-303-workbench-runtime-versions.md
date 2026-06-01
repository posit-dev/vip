# Plan for issue #303: verify expected R/Python versions on the Workbench side

## Context

VIP currently verifies that expected R, Python, and Quarto versions are registered with Connect (via `src/vip_tests/connect/test_runtime_versions.feature`), but does not perform the same verification for Workbench. A customer running UAT identified this gap — they need to confirm that the runtime versions available in Workbench session dialogs match their approved list, with EOL versions excluded.

This is a parallel check to the existing Connect verification, reusing the same `expected_r_versions` and `expected_python_versions` configuration fields from `vip.toml` for allow-list matching, adding deny-list pattern checks for excluded versions, and exercising Workbench's New Session dialog rather than Connect's API.

## Architecture

The implementation follows the four-layer test architecture:

1. **Test layer**: New Gherkin scenarios in `src/vip_tests/workbench/test_runtime_versions.feature` describing the expected behavior in business language.
2. **DSL layer**: Step definitions in `src/vip_tests/workbench/test_runtime_versions.py` orchestrating the test flow using Playwright page objects.
3. **Driver Port layer**: New methods on `WorkbenchClient` or Playwright page classes to query available runtime versions from the New Session dialog.
4. **Driver Adapter layer**: Playwright locators for version selectors in the RStudio and JupyterLab New Session forms.

This mirrors the Connect runtime tests but uses UI automation instead of API calls, since Workbench does not expose a runtime-versions API endpoint.

## Components

**New files:**
- `src/vip_tests/workbench/test_runtime_versions.feature` — Gherkin scenarios for R and Python version verification
- `src/vip_tests/workbench/test_runtime_versions.py` — Step definitions and test functions
- `src/vip_tests/workbench/pages/_new_session_dialog.py` — Page object for the New Session dialog (if not already present; check `pages/` directory for existing dialog helpers)
- `validation_docs/demo-bot-plan-issue-303.md` — Showboat demo proving the plan structure

**Modified files:**
- `src/vip_tests/workbench/pages/__init__.py` — Export new page object class (if created)
- `src/vip/config.py` — add explicit runtime allow-list + deny-list pattern config support for Workbench runtime verification (no optional strict-mode toggle)

## Verification

A reviewer can confirm the plan is structurally sound by:

1. Reading the three proposed scenarios in the issue body and confirming they map cleanly to the four-layer architecture
2. Verifying that `expected_r_versions` and `expected_python_versions` fixtures are already available in `src/vip_tests/conftest.py` (lines 192-198) and can be reused without modification
3. Checking that the existing Workbench test suite already uses Playwright page objects for dialogs (e.g., `test_ide_launch.py` uses `NewSessionDialog`)
4. Confirming that the proposed file structure matches the Connect runtime tests (`src/vip_tests/connect/test_runtime_versions.{feature,py}`)

End-to-end verification requires a live Workbench deployment with multiple R and Python versions configured. Once implemented:

```bash
uv run vip verify --config vip.toml --categories workbench -- -k runtime_versions -v
```

Expected output: three passing scenarios (or fewer if `expected_r_versions` / `expected_python_versions` are not configured in `vip.toml`), including the in-session scenario that verifies the launched RStudio session reports the expected runtime version.

## Scoped decisions

1. **Allow-list and deny-list patterns are in scope** — The implementation will support both expected-version allow-list patterns and excluded-version deny-list patterns for R and Python runtime selectors in the Workbench New Session dialog.

2. **Third scenario is in scope** — The implementation will include and run the in-session runtime verification scenario (RStudio session launches and reports the expected runtime version) in this issue.

3. **UI-based verification is the approach** — Workbench runtime-version checks will use Playwright UI automation. This plan does not assume a Workbench API endpoint for runtime version inventory.

## Out of scope

- **Connect runtime verification changes** — This plan does not modify the existing Connect runtime tests. They remain unchanged and continue to use the Connect API.
- **Quarto version verification for Workbench** — The Connect tests verify Quarto versions; this plan does not add a parallel Workbench check unless explicitly requested.
- **Version comparison logic** — The plan reuses the existing fixture-based version list checks. It does not add semver parsing, range matching, or EOL detection. Those remain out of scope unless the issue evolves.
- **Multi-cluster verification** — This plan assumes a single Workbench deployment. Testing runtime consistency across multiple Workbench servers in a cluster is not covered.
