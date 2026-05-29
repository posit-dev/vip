# Plan for issue #308: Workbench sign-out, AI defaults, runtime extension install

## Context

A customer UAT plan identified three small but distinct coverage gaps in VIP's Workbench test suite. Each represents a real-world validation need that customers expect from a BDD verification tool:

1. **Sign-out flow** — security-sensitive; validates session invalidation
2. **AI features default-off** — compliance requirement for certain deployments
3. **Runtime extension install** — validates OpenVSX-backed deployments where extensions are pulled on demand

These are bundled together because they share a common theme (Workbench IDE testing) but are independent enough to land separately. The issue explicitly asks for three independent PRs, one per gap.

## Architecture

All changes land under `src/vip_tests/workbench/`. The existing `test_auth.feature` gains one scenario (sign-out). Two new feature files are added for AI defaults and runtime extension install. Each new scenario depends on the in-session execution primitive mentioned in the issue, which is tracked separately and not part of this plan.

The plan defers implementation of Gaps 2 and 3 until the session-exec primitive exists. Gap 1 (sign-out) can land immediately because it uses Playwright browser automation on the UI, not terminal access inside a running session.

## Components

**Gap 1 — Sign-out (can land now):**
- `src/vip_tests/workbench/test_auth.feature` — add "User can sign out of Workbench" scenario
- `src/vip_tests/workbench/test_auth.py` — add step definitions for sign-out flow (user menu, sign out button, login page redirect, session cookie invalidation)

**Gap 2 — AI defaults (blocked on session-exec):**
- `src/vip_tests/workbench/test_ai_defaults.feature` — new file with "AI features are disabled by default" scenario outline
- `src/vip_tests/workbench/test_ai_defaults.py` — step definitions for AI provider checks (extension ID absence, settings inspection)
- `src/vip/config.py` — add `[workbench.ai_features]` section with `enabled` boolean field

**Gap 3 — Runtime extension install (blocked on session-exec):**
- `src/vip_tests/workbench/test_runtime_extensions.feature` — new file with "User can install an IDE extension at runtime" scenario outline
- `src/vip_tests/workbench/test_runtime_extensions.py` — step definitions for terminal-based extension install (`code-server --install-extension <id>`) and installed-list verification

## Verification

**Gap 1 (sign-out):**
```bash
uv run vip verify --config vip.toml --categories workbench -- -k "sign out" -v
```
Success: scenario passes, user lands on login page, old cookie fails authentication.

**Gap 2 (AI defaults) and Gap 3 (runtime extensions):**
```bash
uv run vip verify --config vip.toml --categories workbench -- -k "AI features" -v
uv run vip verify --config vip.toml --categories workbench -- -k "runtime extension" -v
```
Success: both scenarios pass, AI providers are absent, runtime extension appears in installed list after terminal install.

All three scenarios must be tagged `@workbench` and auto-skip when Workbench is not configured. Run `just check` to validate lint/format before opening PRs.

## Open questions

- **UNCONFIRMED**: The issue says Gaps 2 and 3 "depend on the in-session execution primitive (separate issue)". That primitive is not yet implemented. Should this plan defer those two gaps until that work lands, or should it include placeholder steps that will be filled in later? **Trade-off**: deferring avoids incomplete scenarios in the suite; placeholders avoid a second round of PRs later.

- **UNCONFIRMED**: Gap 2 proposes checking `github.copilot` extension ID absence and settings inspection. Which settings file (user, workspace, or IDE server config JSON) should be the source of truth? **Trade-off**: user settings are easiest to inspect but can be overridden; server config is authoritative but harder to reach from a test.

- **UNCONFIRMED**: Gap 3 says "user installs a known extension via the IDE terminal". Which extension should be the test subject? It needs to be lightweight, stable, and unlikely to change. **Trade-off**: a first-party Posit extension is stable but may not be in OpenVSX; a generic third-party extension (e.g., `ms-python.python`) is widely available but could be removed.

## Out of scope

- **Session-exec primitive implementation** — tracked in a separate issue (referenced but not detailed in #308). This plan assumes that work lands first for Gaps 2 and 3.
- **Automated cleanup of installed extensions** — Gap 3 installs an extension at runtime. The scenario says "the session is cleaned up" but doesn't specify whether the extension persists after session termination. Out of scope unless the customer's UAT plan explicitly requires cleanup.
- **Multi-IDE coverage beyond VS Code and Positron** — the scenario outlines specify only those two. JupyterLab and RStudio Server are out of scope.
- **Deep AI feature validation** — Gap 2 checks that AI features are disabled by default but doesn't validate the configuration mechanism (e.g., whether `ai.enabled = false` in server config actually disables features). That's a deeper integration test.
