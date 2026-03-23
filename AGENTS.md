# Agent Guidelines for VIP

This document describes how AI coding agents should work with the VIP (Verified Installation of Posit) codebase. Follow these rules when making changes.

## Project overview

VIP is a BDD test suite that validates Posit Team deployments (Connect, Workbench, Package Manager). It uses pytest-bdd with Gherkin `.feature` files, Playwright for browser tests, and httpx for API calls. Test results are written to JSON and rendered into an HTML report with Quarto.

## Environment setup

``` bash
uv sync                          # install dependencies
uv run playwright install chromium
```

Use `uv run` to execute all commands (pytest, ruff, quarto). Do not use bare `python` or `pip` -- everything runs through uv.

## Code quality

Ruff is the linter and formatter. CI enforces both. Always run checks before committing:

``` bash
uv run ruff check src/ tests/ selftests/ examples/
uv run ruff format --check src/ tests/ selftests/ examples/
```

Or with just:

``` bash
just check
```

Ruff rules: `E`, `F`, `I`, `UP`. Line length is 100. All Python directories (`src/`, `tests/`, `selftests/`, `examples/`) must pass. CI pins ruff to version 0.15.0 -- do not change the version without updating `.github/workflows/ci.yml`.

Auto-fix before committing:

``` bash
just fix
```

## Testing

There are two distinct test suites:

### Selftests (`selftests/`)

Framework tests that verify VIP's own config loading, plugin behavior, and reporting module. These run in CI and require no Posit products.

``` bash
uv run pytest selftests/ -v
```

Run selftests after any change to `src/vip/`. If you add new config fields, plugin hooks, or reporting features, add corresponding selftests. Plugin integration tests use the `pytester` fixture (subprocess isolation).

### Product tests (`tests/`)

BDD tests that run against real Posit Team deployments. These are organized by category:

```         
tests/prerequisites/     # Server reachability, auth
tests/package_manager/   # CRAN/PyPI mirrors, repos
tests/connect/           # Auth, deploy, data sources, packages, email
tests/workbench/         # Auth, IDE launch, sessions, packages
tests/cross_product/     # SSL, monitoring, system resources
tests/performance/       # Load times, concurrency
tests/security/          # HTTPS, auth policy, secrets
```

Product tests cannot run in CI (no products available). They are collected with `--collect-only` as a dry run in CI.

## How tests are structured

Every test is a pair of files:

1.  **`.feature` file** -- Gherkin scenarios with a product marker tag
2.  **`.py` file** -- Step definitions using `pytest_bdd`

Example feature file (`tests/connect/test_auth.feature`):

``` gherkin
@connect
Feature: Connect authentication
  Scenario: Admin can log in via the web UI
    Given Connect is accessible at the configured URL
    When I log in with the test credentials
    Then I see the Connect dashboard
```

Example step file (`tests/connect/test_auth.py`):

``` python
from pytest_bdd import scenario, given, when, then

@scenario("test_auth.feature", "Admin can log in via the web UI")
def test_login():
    pass

@given("Connect is accessible at the configured URL")
def connect_accessible(connect_client):
    assert connect_client is not None
```

Key rules:

-   The `@connect`, `@workbench`, or `@package_manager` tag in the feature file controls auto-skip when the product is not configured.
-   Step function names should be descriptive. Use `target_fixture` to pass state between steps.
-   Tests must be non-destructive. Tag created content with `_vip_test` and clean it up in a final `then` step.
-   Use version gating for version-specific features: `@pytest.mark.min_version(product="connect", version="2024.09.0")`

## Four-layer test architecture

VIP structures its tests into four layers, where each layer only communicates with the one directly below it:

```
Layer 1: Test           →  .feature files (Gherkin scenarios)
Layer 2: DSL            →  step definitions + fixtures (pytest_bdd)
Layer 3: Driver Port    →  client interfaces (src/vip/clients/)
Layer 4: Driver Adapter →  httpx (API) or Playwright (UI)
```

When writing new tests, work top-down through each layer. See `docs/test-architecture.md` for the full guide and `/.claude/agents/test-architect.md` for the automated test design agent.

Key principles:
-   Feature files contain only business language -- no URLs, status codes, or selectors.
-   Step definitions are thin; push logic down to the client layer.
-   Client methods return dicts and use raw httpx (no product SDKs).
-   Use `target_fixture` to pass state between steps, not module-level globals.
-   A product API change touches only the client. A UI redesign touches only the Playwright steps. Feature files only change when requirements change.

## Key source files

| File | Purpose |
|------------------------------------|------------------------------------|
| `src/vip/cli.py` | CLI entry point: verify, cleanup, cluster, auth commands |
| `src/vip/config.py` | TOML config loader, dataclasses, `Mode` enum, per-mode validation |
| `src/vip/plugin.py` | pytest plugin: markers, auto-skip, JSON report output |
| `src/vip/reporting.py` | Report data model for Quarto templates |
| `src/vip/clients/connect.py` | httpx client for Connect API |
| `src/vip/clients/workbench.py` | httpx client for Workbench API |
| `src/vip/clients/packagemanager.py` | httpx client for Package Manager API |
| `src/vip/cluster/aws.py` | AWS EKS kubeconfig generation |
| `src/vip/cluster/azure.py` | Azure AKS kubeconfig generation |
| `src/vip/cluster/kubeconfig.py` | Cloud-agnostic kubeconfig writer |
| `src/vip/cluster/target.py` | Cluster config validation |
| `src/vip/verify/site.py` | PTD Site CR parsing, vip.toml generation |
| `src/vip/verify/credentials.py` | Keycloak + interactive credential provisioning |
| `src/vip/verify/job.py` | K8s Job creation, log streaming, cleanup |
| `tests/conftest.py` | Root fixtures: clients, auth, runtimes, data sources |
| `report/index.qmd` | Quarto summary page |
| `report/details.qmd` | Quarto detailed results page |

## Fixtures available in product tests

These are defined in `tests/conftest.py` and available to all tests:

-   `vip_config` -- the full `VIPConfig` object
-   `connect_client` / `workbench_client` / `pm_client` -- httpx API clients (or `None` if not configured)
-   `connect_url` / `workbench_url` / `pm_url` -- product URLs from config
-   `test_username` / `test_password` -- auth credentials
-   `auth_provider` -- e.g. `"password"`, `"saml"`, `"oidc"`, `"oauth2"`
-   `expected_r_versions` / `expected_python_versions` -- version lists from config
-   `data_sources` -- list of `DataSourceEntry` objects
-   `email_enabled` / `monitoring_enabled` -- feature flags

**Note:** `vip verify --connect-url URL` generates configuration on the fly from CLI flags -- no `vip.toml` is needed. When `--k8s` is used, configuration is auto-generated from PTD Site CRs (posit-dev/team-operator).

## API clients

Clients live in `src/vip/clients/` and use plain httpx. Rules:

-   Do not add product SDK dependencies. Use raw HTTP.
-   Return dicts from JSON responses, not custom model objects.
-   Add methods only when tests need them.
-   All clients take a base URL and optional API key in their constructor.

## Configuration

Configuration is in `vip.toml` (see `vip.toml.example` for the template). Secrets come from environment variables:

-   `VIP_CONNECT_API_KEY`
-   `VIP_TEST_USERNAME`
-   `VIP_TEST_PASSWORD`

The plugin loads config via `--vip-config` or defaults to `./vip.toml`. If no config file exists, all product tests are skipped.

## Quarto report

The report lives in `report/` and reads `report/results.json` (written by pytest by default). The `.qmd` files use `IPython.display.Markdown` with `display()` to render content. Always wrap `Markdown()` calls with `display()` -- bare expressions are silently swallowed inside conditionals.

## CI workflows

-   **`ci.yml`** -- ruff lint/format (pinned to 0.15.0) + selftests on Python 3.10 and 3.12. Uses uv cache.
-   **`preview.yml`** -- runs selftests, renders Quarto report, publishes PR preview to gh-pages via `rossjrw/pr-preview-action@v1`. Uses uv and Quarto caches.
-   **`pr-title.yml`** -- validates PR titles follow conventional commit format. Squash merges use the PR title as the commit message.

## PR titles

PR titles must use conventional commit format. CI enforces this via `.github/workflows/pr-title.yml`. Squash merges use the PR title as the commit message, so the title directly becomes the git history.

### Format

```
<type>: <description>
<type>(scope): <description>
```

### Valid types

| Type | Use when |
|------------|----------------------------------------------|
| `feat` | Adding a wholly new feature or capability |
| `fix` | Fixing a bug |
| `docs` | Documentation-only changes |
| `style` | Formatting, whitespace, no code logic changes |
| `refactor` | Code restructuring without behavior changes |
| `perf` | Performance improvements |
| `test` | Adding or updating tests |
| `build` | Build system or dependency changes |
| `ci` | CI workflow or configuration changes |
| `chore` | Maintenance tasks (releases, deps, tooling) |
| `revert` | Reverting a previous commit |

### Rules

-   Scope is optional. Use it to narrow the area of change (e.g. `fix(config): ...`, `feat(connect): ...`).
-   A `!` after the type or scope marks a breaking change (e.g. `feat!: ...`, `fix(config)!: ...`).
-   The description (subject) must not be empty.
-   Do not capitalize the first letter of the description (e.g. `feat: add auth` not `feat: Add auth`).
-   Do not end the description with a period.
-   Keep the title under 70 characters.

### Examples

```
feat: add four-layer test architecture guide
fix(plugin): handle missing config file gracefully
docs: update AGENTS.md with PR title requirements
ci: update PR title check workflow
chore(deps): bump boto3 from 1.42.63 to 1.42.65
refactor(connect)!: rename client constructor parameters
```

### Common mistakes

-   Using an invalid type (e.g. `update`, `change`, `add` — use `feat` or `fix` instead).
-   Capitalizing the description (e.g. `feat: Add feature` — use lowercase `feat: add feature`).
-   Missing the colon and space after the type (e.g. `feat add feature` — must be `feat: add feature`).
-   Using a PR title that is not conventional when the branch will be squash-merged.

## Showboat demos

After completing work on a branch, create a showboat demo that proves your changes work. The demo file is committed to the branch and its contents are pasted into the PR body under a `## Demo` heading.

### Getting started

Run `uvx showboat --help` at the start of a session to learn the tool.

### Creating a demo

``` bash
uvx showboat init demo.md "Feature: <title>"
uvx showboat note demo.md "Explanation of what was done..."
uvx showboat exec demo.md bash "uv run pytest selftests/ -v"
uvx showboat exec demo.md bash "just check"
```

Use `uvx showboat image demo.md <path>` if screenshots are relevant.

### What to demonstrate

-   **New tests:** run the new tests and show them passing
-   **New features:** exercise the feature with concrete examples
-   **Bug fixes:** show the fix in action (before/after if feasible)
-   **Refactors:** show that existing tests still pass
-   **Always** include `just check` (lint/format) output

### Before committing

Use `just demo-save` to verify and move the demo in one step:

``` bash
just demo-save my-feature-name
```

This runs `showboat verify demo.md`, then moves it to `validation_docs/demo-my-feature-name.md`. The root `demo.md` is gitignored and should never be committed directly -- it is a working file only.

### PR workflow

1.  Run `just demo-save <name>` to verify and archive the demo
2.  Commit `validation_docs/demo-<name>.md` with your branch
3.  Paste the contents into the PR body under `## Demo`

CI will run `showboat verify` on any new or changed files in `validation_docs/` for PRs that include them.

## Common mistakes to avoid

-   Forgetting to include `examples/` in ruff check paths.
-   Using `Markdown()` without `display()` in Quarto `.qmd` files.
-   Changing ruff version locally without updating the pinned version in `ci.yml`.
-   Adding product SDK imports (use httpx directly).
-   Writing tests that modify or delete existing customer content.
-   Creating `.py` step files without a matching `.feature` file (or vice versa).
-   Forgetting the `@connect`/`@workbench`/`@package_manager` tag in feature files (breaks auto-skip).
-   Using non-conventional PR titles (must be `type: description`).
