# Plan for issue #303: verify expected R/Python versions on the Workbench side

## Context

VIP currently verifies that expected R, Python, and Quarto versions are registered with Connect (via `src/vip_tests/connect/test_runtime_versions.feature`), but does not perform the same verification for Workbench. A customer running UAT identified this gap — they need to confirm that the runtime versions available in Workbench session dialogs match their approved list, with EOL versions excluded.

This is a parallel check to the existing Connect verification, reusing the same `expected_r_versions` and `expected_python_versions` configuration fields from `vip.toml` but exercising Workbench's New Session dialog rather than Connect's API.

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
- UNCONFIRMED: `src/vip/config.py` — may need to add an optional `unexpected_r_versions: bool` flag under `[runtimes]` to control strict vs. additive version assertions (default `true` for backward compatibility)

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

Expected output: three passing scenarios (or fewer if `expected_r_versions` / `expected_python_versions` are not configured in `vip.toml`).

## Open questions

1. **UNCONFIRMED: Unexpected versions flag** — The issue proposes an optional `unexpected_r_versions: bool` config flag (default `true`) to control whether "no unexpected versions are offered" is enforced. This would allow some customers to use an allow-list approach (strict) while others use additive (only verify expected versions are present, but don't fail if extras exist). The plan assumes this is added to `RuntimesConfig` in `src/vip/config.py`, but the implementation PR may defer this until a customer explicitly requests it.

2. **UNCONFIRMED: Third scenario dependency** — The issue's third scenario ("An RStudio project opens with the expected R version") requires in-session code execution to read `R.version.string`. The issue notes this "depends on the in-session execution primitive (separate issue)". The plan assumes this scenario will be marked `@skip` or deferred to a follow-up PR until that primitive is available.

3. **UNCONFIRMED: Workbench API alternative** — Workbench may expose runtime version information via `/api/server/settings` or a similar endpoint, which would allow simpler API-based verification instead of UI scraping. If such an API exists, the implementation should prefer it for the first two scenarios and only use Playwright for the third (in-session verification). The plan assumes no such API exists based on the Connect/Workbench client code review, but the implementer should confirm.

## Out of scope

- **Connect runtime verification changes** — This plan does not modify the existing Connect runtime tests. They remain unchanged and continue to use the Connect API.
- **Quarto version verification for Workbench** — The Connect tests verify Quarto versions; this plan does not add a parallel Workbench check unless explicitly requested.
- **Version comparison logic** — The plan reuses the existing fixture-based version list checks. It does not add semver parsing, range matching, or EOL detection. Those remain out of scope unless the issue evolves.
- **Multi-cluster verification** — This plan assumes a single Workbench deployment. Testing runtime consistency across multiple Workbench servers in a cluster is not covered.
