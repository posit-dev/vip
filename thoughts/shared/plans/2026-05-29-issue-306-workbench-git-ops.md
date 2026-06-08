# Plan for issue #306: Cover Git operations from Workbench sessions

## Context

VIP currently tests Git only in narrow scenarios (Connect git-backed deployment) and never validates that users inside a Workbench session can clone, commit, and push to Git repositories. This gap affects every Posit Team customer using Git from Workbench sessions. The feature request comes from a customer UAT plan that requires validation of Git operations through both terminal (RStudio, VS Code, Positron) and RStudio's Git GUI against multiple Git providers (GitHub, self-hosted Gitea).

## Architecture

This lands in `src/vip_tests/workbench/` as two new BDD test files: `test_git_terminal.feature` (for CLI-based Git operations across all IDEs) and `test_git_gui.feature` (for RStudio Git pane). The config module (`src/vip/config.py`) gains a new `[workbench.git_test]` block with `clone_url` and `auth_method`. Token lookup is fixed to `VIP_GIT_TOKEN` (same pattern as other product API-key env vars), not user-configurable in TOML. Tests use both `@workbench` and `@if_applicable` so they skip cleanly when Git test config is absent.

### Prerequisite dependency

- **Required before terminal scenario implementation:** session command execution support in `WorkbenchClient` (tracked by #301). The terminal flow (clone/branch/commit/push in-session) depends on this primitive and cannot be implemented reliably without it.

## Components

**Config layer:**
- `src/vip/config.py` — add `GitTestConfig` dataclass with `clone_url: str` and `auth_method: Literal["ssh", "https-token"]`; nest under `WorkbenchConfig.git_test: Optional[GitTestConfig]`
- `src/vip/config.py` — in `GitTestConfig.__post_init__`, hardcode token env lookup to `VIP_GIT_TOKEN`

**Test layer:**
- `src/vip_tests/workbench/test_git_terminal.feature` — three separate named scenarios (RStudio, VS Code, Positron), not a Scenario Outline; feature tagged with both `@workbench` and `@if_applicable`
- `src/vip_tests/workbench/test_git_terminal.py` — step definitions using terminal execution in session, git commands, and remote verification
- `src/vip_tests/workbench/test_git_gui.feature` — RStudio Git pane scenario (Playwright-driven), tagged `@workbench @if_applicable`
- `src/vip_tests/workbench/test_git_gui.py` — step definitions using Playwright to interact with RStudio Git pane

**Shared fixtures:**
- `src/vip_tests/conftest.py` — add `git_test_config` fixture (returns `vip_config.workbench.git_test` or skip), `git_test_token` fixture (loads `VIP_GIT_TOKEN`), and two-layer cleanup for pushed branches:
  - explicit `Then` cleanup step in scenario flow
  - session-scoped autouse finalizer safety net (mirroring `_cleanup_sessions` / `_wb_cleanup_state`)

**Client enhancements (if needed):**
- `src/vip/clients/workbench.py` — verify session execution primitives exist; add if missing

## Verification

**Config parsing:**
```bash
# Add [workbench.git_test] block to vip.toml, run config validation
uv run pytest selftests/test_config.py -k git_test -v
```

Add `GitTestConfig` selftests covering:
- TOML round-trip
- `VIP_GIT_TOKEN` env fallback
- `is_configured` property
- `from_dict` default handling

**Terminal scenarios:**
```bash
# Requires a live Workbench + configured Git test repo
export VIP_GIT_TOKEN=<token>
uv run vip verify --config vip.toml --categories workbench -- -k test_git_terminal -v
```

**GUI scenario:**
```bash
# Requires Playwright browser + live Workbench
uv run vip verify --config vip.toml --categories workbench -- -k test_git_gui -v
```

Success: all scenarios pass, cleanup deletes pushed branches (verified with `git ls-remote`), tests skip cleanly when `[workbench.git_test]` is absent, and branch names follow `vip<timestamp>` (aligned with `unique_session_name` style for low-collision cleanup-friendly runs).

## Open questions

- Confirm exact API shape for `WorkbenchClient` session command execution from #301 so terminal steps can use it directly.

## Out of scope

- SSH authentication (issue notes say "start with HTTPS + token to keep the first PR small")
- Testing against multiple Git providers in a single run (config accepts one `clone_url`; parameterization is left to the user's test matrix)
- Non-RStudio Git GUI interactions (VS Code and Positron have their own Git UIs; terminal coverage is sufficient for those IDEs)
- Git operations from Connect or Package Manager (out of domain for this issue)
