# Plan for issue #306: Cover Git operations from Workbench sessions

## Context

VIP currently tests Git only in narrow scenarios (Connect git-backed deployment) and never validates that users inside a Workbench session can clone, commit, and push to Git repositories. This gap affects every Posit Team customer using Git from Workbench sessions. The feature request comes from a customer UAT plan that requires validation of Git operations through both terminal (RStudio, VS Code, Positron) and RStudio's Git GUI against multiple Git providers (GitHub, self-hosted Gitea).

## Architecture

This lands in `src/vip_tests/workbench/` as two new BDD test files: `test_git_terminal.feature` (for CLI-based Git operations across all IDEs) and `test_git_gui.feature` (for RStudio Git pane). The config module (`src/vip/config.py`) gains a new `[workbench.git_test]` block with `clone_url`, `auth_method`, and token reference. The workbench client (`src/vip/clients/workbench.py`) may need session execution helpers if they don't exist. Tests use the existing `@workbench` marker and skip cleanly when Git test config is absent.

## Components

**Config layer:**
- `src/vip/config.py` — add `GitTestConfig` dataclass with `clone_url: str`, `auth_method: Literal["ssh", "https-token"]`, and `token_env_var: str` (default `VIP_GIT_TOKEN`); nest under `WorkbenchConfig.git_test: Optional[GitTestConfig]`

**Test layer:**
- `src/vip_tests/workbench/test_git_terminal.feature` — scenario outline for clone, branch, commit, push via terminal across RStudio / VS Code / Positron
- `src/vip_tests/workbench/test_git_terminal.py` — step definitions using terminal execution in session, git commands, and remote verification
- `src/vip_tests/workbench/test_git_gui.feature` — RStudio Git pane scenario (Playwright-driven)
- `src/vip_tests/workbench/test_git_gui.py` — step definitions using Playwright to interact with RStudio Git pane

**Shared fixtures:**
- `src/vip_tests/conftest.py` — add `git_test_config` fixture (returns `vip_config.workbench.git_test` or skip), `git_test_token` fixture (loads from env var), and cleanup helpers for pushed branches

**Client enhancements (if needed):**
- `src/vip/clients/workbench.py` — verify session execution primitives exist; add if missing

## Verification

**Config parsing:**
```bash
# Add [workbench.git_test] block to vip.toml, run config validation
uv run pytest selftests/config/ -k git_test -v
```

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

Success: all scenarios pass, cleanup deletes pushed branches (verified with `git ls-remote`), tests skip cleanly when `[workbench.git_test]` is absent.

## Open questions

- UNCONFIRMED: Does the workbench client already have a session execution primitive (run command in terminal, get output)? If not, this plan needs that built first.
- UNCONFIRMED: Should branch naming use `vip-test-` prefix or `vip-` with timestamp? Timestamp ensures uniqueness but makes cleanup harder.
- UNCONFIRMED: Should cleanup happen in a final step (as shown in proposed scenarios) or in a pytest finalizer? Finalizers are more robust but the issue's proposed Gherkin includes explicit cleanup steps.

## Out of scope

- SSH authentication (issue notes say "start with HTTPS + token to keep the first PR small")
- Testing against multiple Git providers in a single run (config accepts one `clone_url`; parameterization is left to the user's test matrix)
- Non-RStudio Git GUI interactions (VS Code and Positron have their own Git UIs; terminal coverage is sufficient for those IDEs)
- Git operations from Connect or Package Manager (out of domain for this issue)
