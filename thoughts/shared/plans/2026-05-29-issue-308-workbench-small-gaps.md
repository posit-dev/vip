# Plan for issue #308: Workbench sign-out, AI defaults, runtime extension install

## Context

A customer UAT plan identified three small but distinct coverage gaps in VIP's Workbench test suite. Each represents a real-world validation need that customers expect from a BDD verification tool:

1. **Sign-out flow** — security-sensitive; validates session invalidation
2. **AI features default-off** — compliance requirement for certain deployments
3. **Runtime extension install** — validates OpenVSX-backed deployments where extensions are pulled on demand

These are bundled together because they share a common theme (Workbench IDE testing) but are independent enough to land separately. The issue explicitly asks for three independent PRs, one per gap.

## Architecture

All changes land under `src/vip_tests/workbench/`, with config updates in `src/vip/config.py` and config selftests in `selftests/test_config.py`.

- **Gap 1 (sign-out)** is independent and can land immediately (Playwright UI automation only).
- **Gap 2 (AI defaults)** is investigated via `WorkbenchClient.server_settings()` first. If AI/Copilot flags are exposed by `/api/server/settings`, this gap is unblocked and implemented as an API assertion test with no session-exec dependency.
- **Gap 2 fallback** (only if `/api/server/settings` succeeds but omits the required AI/Copilot keys) is deferred pending #301 session-exec support for in-session server config inspection.
- **Gap 3 (runtime extension install)** depends on #301 session-exec (`ide_terminal_run` / `code-server --install-extension`) and is deferred until that lands. See #301.

## Components

**Gap 1 — Sign-out (can land now):**
- `src/vip_tests/workbench/test_auth.feature` — add "User can sign out of Workbench" scenario
- `src/vip_tests/workbench/test_auth.py` — add step definitions for sign-out flow (user menu, sign out button, login page redirect, session cookie invalidation)

**Gap 2 — AI defaults (API-first; fallback depends on #301 only if needed):**
- `src/vip_tests/workbench/test_ai_defaults.feature` — new file with "AI features are disabled by default" scenario outline
- `src/vip_tests/workbench/test_ai_defaults.py` — first assert deployment defaults from `WorkbenchClient.server_settings()` (`/api/server/settings`), and only fall back to in-session config inspection when the API call succeeds but the expected AI/Copilot keys are absent from the returned JSON payload
- `src/vip/config.py` — add `[workbench.ai_features]` config block for deployment-level expected defaults
- `selftests/test_config.py` — add coverage for parsing `[workbench.ai_features]`

**Gap 3 — Runtime extension install (blocked on session-exec):**
- `src/vip_tests/workbench/test_runtime_extensions.feature` — new file with "User can install an IDE extension at runtime" scenario outline
- `src/vip_tests/workbench/test_runtime_extensions.py` — step definitions for terminal-based extension install (`code-server --install-extension <id>`) and installed-list verification
- `src/vip/config.py` — add `workbench.test_extension` (single extension ID) so deployments provide an OpenVSX-available extension to test
- Default extension should be OpenVSX-verified (e.g. `redhat.vscode-yaml` or `vscodevim.vim`), explicitly not `ms-python.python`

## Verification

1. Run sign-out coverage:
   ```bash
   uv run vip verify --config vip.toml --categories workbench -- -k "sign out" -v
   ```
   Success: scenario passes, user lands on login page, old cookie fails authentication.
2. Run AI defaults coverage (API-first assertion):
   ```bash
   uv run vip verify --config vip.toml --categories workbench -- -k "AI features" -v
   ```
   Success: scenario passes via `/api/server/settings`; fallback path is only used when the API does not expose the required flag.
3. Run runtime extension coverage (after #301 lands):
   ```bash
   uv run vip verify --config vip.toml --categories workbench -- -k "runtime extension" -v
   ```
   Success: scenario passes with a configured OpenVSX-backed extension ID after terminal install.
4. Run repository checks:
   ```bash
   just check
   ```

All three scenarios must be tagged `@workbench` and auto-skip when Workbench is not configured.

## Open questions

- None for this planning pass. Gap 2 and Gap 3 dependencies are now explicit and scoped per-gap.

## Out of scope

- **Session-exec primitive implementation** — tracked in a separate issue (#301). This plan only depends on it for Gap 3 and for Gap 2's fallback path if `/api/server/settings` does not expose the required AI flags.
- **Automated cleanup of installed extensions** — Gap 3 installs an extension at runtime. The scenario says "the session is cleaned up" but doesn't specify whether the extension persists after session termination. Out of scope unless the customer's UAT plan explicitly requires cleanup.
- **Multi-IDE coverage beyond VS Code and Positron** — the scenario outlines specify only those two. JupyterLab and RStudio Server are out of scope.
- **Deep AI feature validation** — Gap 2 checks that AI features are disabled by default but doesn't validate the configuration mechanism (e.g., whether `ai.enabled = false` in server config actually disables features). That's a deeper integration test.
