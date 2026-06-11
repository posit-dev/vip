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
- **Gap 2 fallback** (only if `/api/server/settings` succeeds but omits the required AI/Copilot keys) can now use `exec.terminal_run` for in-session config inspection — the session-exec primitive landed in #349.
- **Gap 3 (runtime extension install)** is now unblocked: `exec.terminal_run` (merged in #349) can drive `code-server --install-extension` from the IDE terminal. No external dependency remains.

## Components

**Gap 1 — Sign-out (can land now):**
- `src/vip_tests/workbench/test_auth.feature` — add "User can sign out of Workbench" scenario
- `src/vip_tests/workbench/test_auth.py` — add step definitions for sign-out flow (user menu, sign out button, login page redirect, session cookie invalidation)
- Reuse existing selectors already defined in the codebase:
  - `src/vip_tests/workbench/pages/ide_base.py:11` — `IDEBase.SIGN_OUT_BTN = "[title='Sign out']"` (in-IDE sign-out button)
  - `src/vip_tests/workbench/pages/homepage.py:78-79` — `Homepage.SIGN_OUT_FORM = "form[action*='sign-out']"` and `Homepage.SIGN_OUT_BTN_OLD = "#signOutBtn"` (homepage sign-out path)

**Gap 2 — AI defaults (API-first; fallback via exec.terminal_run if needed):**
- `src/vip_tests/workbench/test_ai_defaults.feature` — new file with "AI features are disabled by default" scenario outline
- `src/vip_tests/workbench/test_ai_defaults.py` — first assert deployment defaults from `WorkbenchClient.server_settings()` (`/api/server/settings`), and only fall back to in-session config inspection (via `exec.terminal_run`) when the API call succeeds but the expected AI/Copilot keys are absent from the returned JSON payload. The fallback is now available without waiting for any external issue — `terminal_run` shipped in #349.
- `src/vip/config.py` — add `[workbench.ai_features]` config block for deployment-level expected defaults
- `selftests/test_config.py` — add coverage for parsing `[workbench.ai_features]`

**Gap 3 — Runtime extension install (now unblocked via #349):**
- `src/vip_tests/workbench/test_runtime_extensions.feature` — new file with "User can install an IDE extension at runtime" scenario outline
- `src/vip_tests/workbench/test_runtime_extensions.py` — step definitions drive terminal-based extension install using `exec.terminal_run(page, "code-server --install-extension <id>", ...)` and verify the installed extension via a follow-up terminal or console command. The session-exec primitive (`terminal_run`, `read_file`, `file_exists` at `src/vip_tests/workbench/exec.py:325,389,413`) is available today.
- `src/vip/config.py` — add `workbench.test_extension` (single extension ID string) following the same pattern as `test_packages` (`list[str] = field(default_factory=list)`, parsed in `from_dict` via `raw.get("test_extension", "")`, validated in `selftests/test_config.py`). Default extension should be OpenVSX-verified (e.g. `redhat.vscode-yaml` or `vscodevim.vim`), explicitly not `ms-python.python`.

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
   Success: scenario passes via `/api/server/settings`; fallback via `exec.terminal_run` is only used when the API does not expose the required flag.
3. Run runtime extension coverage:
   ```bash
   uv run vip verify --config vip.toml --categories workbench -- -k "runtime extension" -v
   ```
   Success: scenario passes with a configured OpenVSX-backed extension ID after terminal install via `exec.terminal_run`.
4. Run repository checks:
   ```bash
   just check
   ```

All three scenarios must be tagged `@workbench` and auto-skip when Workbench is not configured.

## Open questions

- None. All three gaps are unblocked: Gap 1 is Playwright-only, Gap 2's fallback and Gap 3 both use `exec.terminal_run` which landed in #349.

## Out of scope

- **Session-exec primitive implementation** — already shipped in #349. This plan only consumes it.
- **Automated cleanup of installed extensions** — Gap 3 installs an extension at runtime. The scenario says "the session is cleaned up" but doesn't specify whether the extension persists after session termination. Out of scope unless the customer's UAT plan explicitly requires cleanup.
- **Multi-IDE coverage beyond VS Code and Positron** — the scenario outlines specify only those two. JupyterLab and RStudio Server are out of scope.
- **Deep AI feature validation** — Gap 2 checks that AI features are disabled by default but doesn't validate the configuration mechanism (e.g., whether `ai.enabled = false` in server config actually disables features). That's a deeper integration test.
