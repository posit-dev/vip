# Agent Guidelines for VIP

This document describes how AI coding agents should work with the VIP (Verified Installation of Posit) codebase. Follow these rules when making changes.

## Project overview

VIP is a BDD test suite that validates Posit Team deployments (Connect, Workbench, Package Manager). It uses pytest-bdd with Gherkin `.feature` files, Playwright for browser tests, and httpx for API calls. Test results are written to JSON and rendered into an HTML report with Quarto.

## Environment setup

``` bash
uv sync                          # install dependencies
uv run vip install               # system packages (dnf/apt) + Playwright Chromium
```

`vip install` detects the platform (RHEL family, Debian/Ubuntu, macOS), installs
only the Chromium runtime libs that are missing, and records what it added to
`.vip-install.json` so `vip uninstall` can reverse exactly those changes. On
non-root Linux it prints the `sudo dnf install` / `sudo apt install` command for
you to run, then claims those packages on the next `vip install` run.

Use `uv run` to execute all commands (pytest, ruff, quarto). Do not use bare `python` or `pip` -- everything runs through uv.

## Code quality

Ruff is the linter and formatter. CI enforces both. Always run checks before committing:

``` bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/
uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
```

Or with just:

``` bash
just check
```

Ruff rules: `E`, `F`, `I`, `UP`. Line length is 100. All Python directories (`src/`, `src/vip_tests/`, `selftests/`, `examples/`) must pass. CI pins ruff to version 0.15.0 -- do not change the version without updating `.github/workflows/ci.yml`.

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

### Product tests (`src/vip_tests/`)

BDD tests that run against real Posit Team deployments. These are organized by category:

```         
src/vip_tests/prerequisites/     # Server reachability, auth
src/vip_tests/package_manager/   # CRAN/PyPI mirrors, repos
src/vip_tests/connect/           # Auth, deploy, data sources, packages, email
src/vip_tests/workbench/         # Auth, IDE launch, sessions, packages
src/vip_tests/cross_product/     # SSL, monitoring, system resources
src/vip_tests/performance/       # Load times, concurrency
src/vip_tests/security/          # HTTPS, auth policy, secrets
```

Product tests cannot run in CI (no products available). They are collected with `--collect-only` as a dry run in CI.

Run a specific category of product tests:

``` bash
uv run vip verify --config vip.toml --categories package-manager -- -v
```

Pass extra pytest args after `--` (e.g. `-k pattern` to filter, `-v` for verbose).

## How tests are structured

Every test is a pair of files:

1.  **`.feature` file** -- Gherkin scenarios with a product marker tag
2.  **`.py` file** -- Step definitions using `pytest_bdd`

Example feature file (`src/vip_tests/connect/test_auth.feature`):

``` gherkin
@connect
Feature: Connect authentication
  Scenario: Admin can log in via the web UI
    Given Connect is accessible at the configured URL
    When I log in with the test credentials
    Then I see the Connect dashboard
```

Example step file (`src/vip_tests/connect/test_auth.py`):

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
| `src/vip/cli.py` | CLI entry point: version, verify (including `--basic` to skip `@slow`-tagged scenarios), cleanup (Connect content + orphaned Workbench sessions via `--workbench-url`), install, uninstall, auth, scaffold commands; `--version` flag |
| `src/vip/config.py` | TOML config loader and dataclasses (includes `[proxy]` → `ProxyConfig`) |
| `src/vip/proxy.py` | Single source of truth for outbound-proxy resolution. `ProxyConfig` + `build_proxy_map` (mirrors httpx's `get_environment_proxies`, incl. NO_PROXY formatting), `build_mounts` (per-scheme `HTTPTransport` mounts that keep `verify`), `proxy_for_url` (httpx-identical most-specific-pattern selection, used by non-httpx probes), `playwright_proxy` (renders a Playwright `launch(proxy=)` dict). Every HTTP egress path routes through this so VIP never diverges from httpx's own env-proxy behavior — see "Outbound proxy support" below |
| `src/vip/auth.py` | Interactive and headless browser authentication for OIDC providers; `authenticated_page` opens a headless page from a cached auth session for `vip cleanup --workbench-url`; `auth_cache_path()` is the single source of truth for the `.vip-auth-cache.json` location (both `plugin.py` and `cli.py` must use it), and `_load_cached_auth` probes Workbench before trusting a cached session; `refresh_auth_cache_from_storage_state` writes a live context's cookies back over a cache whose session has been invalidated (atomic, 0600, existing caches only) |
| `src/vip/idp.py` | IdP login form strategies for headless auth (Keycloak, Okta) |
| `src/vip/plugin.py` | pytest plugin: markers (including `slow`, used by `verify --basic`), auto-skip, JSON report output |
| `src/vip/version.py` | `ProductVersion` parsing/comparison for `min_version` gating; `MINIMUM_SUPPORTED_POSIT_TEAM` support floor (powers `vip version`) |
| `src/vip/workbench_ui.py` | Browser-driven Workbench session-cleanup sweep (`quit_vip_sessions_via_ui`), shared by the per-test cleanup fixture and `vip cleanup --workbench-url`; takes an `owner` so a per-test sweep only quits its own xdist worker's sessions |
| `src/vip/reporting.py` | Report data model for Quarto templates |
| `src/vip/clients/connect.py` | httpx client for Connect API |
| `src/vip/clients/workbench.py` | httpx client for Workbench API; `quit_vip_sessions` warns loudly (not silently) when a VIP session persists after all retries. `session_owner` / `is_vip_session_for_owner` decide whether a VIP session belongs to the sweeping worker — see "Session ownership" below |
| `src/vip/clients/packagemanager.py` | httpx client for Package Manager API |
| `src/vip/install/platform.py` | Distro detection (rhel/debian/macos) + canonical Chromium package lists |
| `src/vip/install/manifest.py` | `.vip-install.json` read/write (atomic), schema gate, pending-package helpers |
| `src/vip/install/packages.py` | `rpm -q` / `dpkg-query` wrappers for pre-existing detection |
| `src/vip/install/playwright.py` | Playwright cache detection + `playwright install chromium` wrapper |
| `src/vip/install/plan.py` | Pure `build_install_plan` / `build_uninstall_plan` builders |
| `src/vip/install/runner.py` | Plan executor: dry-run formatting + execute (system packages, Playwright, manifest writes) |
| `src/vip_tests/conftest.py` | Root fixtures: clients, auth, runtimes, data sources |
| `report/index.qmd` | Quarto summary page |
| `report/details.qmd` | Quarto detailed results page |

## Extension examples

VIP ships two canonical extension examples in `examples/`:

| Directory | Purpose |
|---|---|
| `examples/custom_tests/` | Minimal HTTP health-check extension (simpler starting point) |
| `examples/cross_product_validation/` | GxP/regulated-environment pattern: runtime version checks + DESeq2/PyDeSEQ2 package installability across Connect and Workbench |

Generate the cross-product example in a new directory with:

```bash
vip scaffold --output ./my-custom-tests
```

When writing a new extension example, follow the same four-layer architecture and add
`@pytest.mark.connect` / `@pytest.mark.workbench` decorators to every `@scenario` function so
auto-skip works correctly (feature-level Gherkin tags alone are not sufficient).

## Fixtures available in product tests

These are defined in `src/vip_tests/conftest.py` and available to all tests:

-   `vip_config` -- the full `VIPConfig` object
-   `connect_client` / `workbench_client` / `pm_client` -- httpx API clients (or `None` if not configured)
-   `connect_url` / `workbench_url` / `pm_url` -- product URLs from config
-   `test_username` / `test_password` -- auth credentials
-   `auth_provider` -- e.g. `"password"`, `"saml"`, `"oidc"`, `"oauth2"`
-   `expected_r_versions` / `expected_python_versions` -- version lists from config
-   `data_sources` -- list of `DataSourceEntry` objects
-   `email_enabled` / `monitoring_enabled` -- feature flags

**Note:** `vip verify --connect-url URL` generates configuration on the fly from CLI flags -- no `vip.toml` is needed.

## API clients

Clients live in `src/vip/clients/` and use plain httpx. Rules:

-   Do not add product SDK dependencies. Use raw HTTP.
-   Return dicts from JSON responses, not custom model objects.
-   Add methods only when tests need them.
-   All clients take a base URL and optional API key in their constructor.
-   `BaseClient` needs a custom `transport=` (for `retries` and transport-level `verify`), which makes httpx ignore env proxies. It therefore resolves the proxy itself via `vip.proxy` and passes per-scheme `mounts=`. Any new ad-hoc `httpx.get`/`httpx.Client` in the client layer must route through the same proxy — pass `proxy=proxy_for_url(url, self._proxy_map)` (see `fetch_content`), never rely on httpx's ambient env pickup, so an explicit `[proxy]` config applies uniformly. See "Outbound proxy support" below.

## Configuration

Configuration is in `vip.toml` (see `vip.toml.example` for the template). Secrets come from environment variables:

-   `VIP_CONNECT_API_KEY`
-   `VIP_TEST_USERNAME`
-   `VIP_TEST_PASSWORD`
-   `VIP_TEST_TOTP_SECRET` — optional base32 TOTP seed used by `--headless-auth` to auto-fill MFA codes for a dedicated test service account. **Equivalent to bypassing 2FA — never use a personal account's seed.**

The plugin loads config via `--vip-config` or defaults to `./vip.toml`. If no config file exists, all product tests are skipped.

## Outbound proxy support

VIP talks to deployments over three different HTTP mechanisms, and left alone they disagree about proxies: a custom-transport `httpx.Client` (the product API clients) silently ignores `HTTP_PROXY`/`HTTPS_PROXY` — httpx computes `allow_env_proxies = trust_env and transport is None`, so a supplied transport turns env-proxy resolution off — while bare `httpx.get` honors it, and Playwright's Chromium does its own platform-dependent env detection. That split is what makes the Connect API-key flow fail behind a proxy: mint/probe succeed through the proxy, then the ConnectClient calls go direct (or vice-versa).

`src/vip/proxy.py` is the single source of truth that makes every path agree. The invariant: **all outbound HTTP egress resolves its proxy through `vip.proxy`, and no code relies on httpx's ambient env pickup.** Concretely:

- **Product clients** (`BaseClient`): resolve `build_proxy_map` at construction, pass per-scheme `mounts=` (each an `HTTPTransport` carrying `verify`) alongside the base transport. `self._proxy_map` is exposed for ad-hoc calls.
- **Bare httpx call sites** (auth mint/probe/delete, cache-liveness probe, `fetch_content`, scheme resolution): pass an explicit `proxy=proxy_for_url(url, build_proxy_map(proxy))` **and** `trust_env=False`, so the resolved per-URL proxy (which honors NO_PROXY) is authoritative rather than httpx re-reading the env.
- **Playwright** (`_launch_chromium`, and the in-suite `browser_context_args`): pass `proxy=playwright_proxy(build_proxy_map(proxy), target_url)` so the browser shares the same proxy. Always pass the URL that browser is about to navigate. Playwright takes one `server` per browser and rewrites it to a single `scheme://host:port` (its `normalizeProxySettings`), so Chromium's per-scheme `--proxy-server=http=a;https=b` form is unavailable — `target_url`'s scheme is what keeps the browser on the same gateway as httpx when `HTTP_PROXY` and `HTTPS_PROXY` differ and the product is served over plain http. `target_url` chooses *which* proxy, never *whether*: a bypassed target still returns a dict, because the login browser also navigates the IdP, which usually is not bypassed.

`ProxyConfig` (from `[proxy]` in `vip.toml`, or `--proxy`/`--no-proxy`) threads from `VIPConfig.proxy` through the conftest client fixtures, the plugin auth entrypoints, and every `cli.py` command. Default (`trust_env=True`, no `url`) reads the ambient environment exactly as httpx would — so the no-config case is unchanged.

**One deliberate divergence from httpx** (`_promote_http_proxy_to_https`): httpx keys its env map by *target* scheme, so a lone `HTTP_PROXY` (no `HTTPS_PROXY`/`ALL_PROXY`) yields `{'http://': …}` and httpx sends **https direct**. Many orgs run a single forward proxy as their *only* outbound tunnel and set just `http_proxy`, expecting https to tunnel through it via `CONNECT`; on a proxy-only network httpx's default means VIP's https traffic can never leave the host. So when the env gives an `http://` proxy with no explicit https/all coverage, `build_proxy_map` promotes it to cover `https://` too — applied to the whole map, so `proxy_for_url`, `build_mounts`, and `playwright_proxy` all agree (browser and API take the same route by construction). An explicit `HTTPS_PROXY`/`ALL_PROXY` is never overridden, and `NO_PROXY` still bypasses. This is why `build_proxy_map` is *not* byte-for-byte identical to `get_environment_proxies` in the http-only case.

Two Chromium-specific edges to keep in mind when touching `playwright_proxy`:
- **Bypass patterns keep their `*`.** httpx renders `NO_PROXY=example.com` as `all://*example.com`, matching the apex *and* subdomains. Chromium reads a bare `example.com` as an exact-host match, so `_pattern_to_bypass_host` must not strip the leading `*` — doing so makes the browser proxy exactly the subdomains httpx reaches directly, and products live on subdomains. Playwright forwards `*example.com` untouched (it only prepends `*` to entries already starting with `.`).
- **`--proxy`/`--no-proxy` only reach the generated temp config.** Any run that loads a config file — `--config` *or* the default `./vip.toml` — has no consumer for them, so `run_verify` warns. Key that warning on "no temp config was generated", not on `config_path`, which is still `None` on the default-resolution path.

Two sharp edges the fix also closes:
- **Scheme downgrade** (`resolve_url_scheme`): a `ProxyError` must never trigger the `https://`→`http://` fallback (it says nothing about the origin's TLS), and when a proxy applies the raw-socket TLS-listener tiebreak is skipped entirely (it bypasses the proxy, so its "nothing is listening" verdict is about a path VIP will never take). Downgrading there would send credentials in cleartext on a proxy-only host.
- **retries**: httpx's `HTTPProxy` pool drops the `retries` value (only the direct `ConnectionPool` keeps it). Proxied requests therefore get no connection-retries; this matches httpx and is documented in `proxy.py`, not worked around.

If you add a new HTTP egress path, route it through `vip.proxy` — do not reintroduce a raw `httpx.get`/socket that bypasses the proxy.

**Deliberately scoped out (env-proxy only, not the explicit `[proxy]` config).** A few opt-in/diagnostic paths still use bare `httpx.get` with httpx's default `trust_env=True`, so they honor the ambient `HTTP(S)_PROXY`/`NO_PROXY` env but not an explicit `[proxy]` TOML/`--proxy` config: the test-layer probes in `src/vip_tests/**` (e.g. `prerequisites/test_components.py`, `performance/*`, `security/*`, `package_manager/*`, `cross_product/test_resources.py`, `helpers.py`), the load/perf engine (`src/vip/load_engine.py`, gated behind the `performance` category), and the raw-socket TLS probes in `cross_product/test_ssl.py` / `security/test_https.py` (which test the *plaintext/handshake* boundary and are intentionally direct). The Kubernetes client (`clients/kubernetes.py`) uses the `kubernetes` SDK (urllib3), not httpx, and is out of scope. These are consistent for the common env-var case (the customer's `HTTPS_PROXY`); wiring them to the explicit `[proxy]` config would mean threading `ProxyConfig` into `PerformanceConfig` and every test helper — worth doing only if a deployment needs an explicit proxy that differs from the environment.

## Workbench session ownership (parallel safety)

Every Workbench session VIP creates encodes the xdist worker that created it, and cleanup uses that to decide what it may quit. This is not cosmetic: a sweep that matches on the bare `VIP ` prefix quits sessions a *sibling worker is still driving*, which surfaces as a vanished session row, an "Abnormal exits" toast, a `Session status: Quit` banner inside a live IDE, or `jsonrpc error 1 (Unable to connect to service)` in an RStudio console — all of them looking like deployment faults rather than a test-suite bug.

The naming contract:

| Generator | Format | Example |
|---|---|---|
| `unique_session_name(filename)` | `VIP <file> - <worker>-<ns>` | `VIP test_git_ops.py - gw1-1785380284140718000` |
| `vip_session_prefix(kind)` | `_vip_<kind>_<worker>_<ts>_` | `_vip_cap_gw1_1785380282_Small_0` |

All of them live in `src/vip_tests/workbench/conftest.py` next to `current_worker_id()`, and `vip.clients.workbench.session_owner` parses the worker back out.

**Name every session through one of those two helpers.** Scenarios that don't fit `unique_session_name` (capacity, k8s capacity) take a thin wrapper over `vip_session_prefix` — `capacity_session_prefix()`, `k8s_session_prefix()` — rather than formatting a prefix by hand. `_VIP_OWNER_PATTERNS` is generic over `<kind>`, so a new scheme routed through the helper is attributable for free; a hand-rolled one that omits the worker segment is treated as unowned, and unowned means **no in-run sweep will ever clean it up**. That is exactly how `_vip_k8s_` sessions started leaking when worker scoping first landed. If you change either format, update `_VIP_OWNER_PATTERNS` in `src/vip/clients/workbench.py` in the same commit.

Rules for cleanup code:

- Anything running *during* a test run (the autouse `_cleanup_sessions` fixture, the per-worker end-of-run sweep) must pass `owner=current_worker_id()`.
- Only `vip cleanup --workbench-url` sweeps globally (`owner=None`), because it runs when no worker is left to disturb. That is also what clears orphans a crashed worker left behind, and orphans from an older VIP whose names carry no worker segment.

## Quarto report

The report lives in `report/` and reads `report/results.json` (written by pytest by default). The `.qmd` files use `IPython.display.Markdown` with `display()` to render content. Always wrap `Markdown()` calls with `display()` -- bare expressions are silently swallowed inside conditionals.

## CI workflows

-   **`ci.yml`** -- on every PR/push: ruff lint/format (pinned to 0.15.0), mypy type-check, zizmor actions-lint, a runtime dependency audit, and selftests (Ubuntu + macOS, Python 3.10 and 3.12). A `changes` path-filter gates the expensive jobs, while `Lint & Format`, `Selftests Status` and `CI Status` always run as required checks. Uses uv cache. `CI Status` is the scope-aware aggregator for the four path-gated jobs (`Type Check`, `Actions Lint (zizmor)`, `Dependency Audit`, `Lockfile Guard`): none of them can be a required check directly, because each is conditional on `changes` and a failed change-detection job would skip them all and report a green gate. A legitimately skipped job counts as passing; only failure or cancellation is fatal.
-   **`preview.yml`** -- runs selftests, renders Quarto report, publishes PR preview to gh-pages via `rossjrw/pr-preview-action@v1`. Uses uv and Quarto caches.
-   **`pr-title.yml`** -- validates PR titles follow conventional commit format. Squash merges use the PR title as the commit message.
-   **`release.yml`** -- cuts VIP's calver release train: `schedule` (Thursday evenings) plus `workflow_dispatch` for out-of-band releases. `scripts/next_version.py` computes the version (`YYYY.M.0` for the first release of a calendar month, `YYYY.M.PATCH` for later ones that month); a scheduled or blank-`version` dispatch run exits cleanly when there are no commits since the last tag, while a dispatch run with an explicit `version` skips that gate but must still be strictly greater than the last release. `cliff.toml` (git-cliff) generates the `CHANGELOG.md` entry for the tag before it exists, so it lands inside the release commit rather than needing a second commit. `just relock` keeps `uv.lock`'s own `posit-vip` entry in sync with the version just stamped -- see docs/development.md ("Versioning and the release cadence") for the full rule and issue #559 for why the relock step matters.
-   **Smoke workflows** (`connect-smoke.yml`, `workbench-smoke.yml`, `packagemanager-smoke.yml`, `mock-idp-e2e.yml`) -- run the product suites against real containers. On PR/push each tests a single latest version (change-gated via a `changes` paths-filter job); on `schedule` (nightly, staggered hourly) and `workflow_dispatch` a `set-matrix` job fans each out across the product version support window (current + 2 back). Bump the pinned tags in each workflow's `set-matrix` step when a new product release ships. Each workflow's `*-status` aggregation job is scope-aware: it passes when the suite was legitimately out of scope (the PR's paths didn't match) but **fails** when the suite was in scope (`changes.relevant == 'true'`) yet did not succeed -- so a path-gated skip, an excluded actor, or a missing license secret can no longer report a green required check without the suite having run. The Connect, Workbench, and Package Manager `*-status` jobs are required merge checks.
    `mock-idp-e2e.yml` is structured the same way so `Mock-IdP E2E Status` can be promoted to a required check via a separate admin action.
    `workbench-smoke.yml` additionally splits into two tiers via a `suite` value: PR/push runs `gate` (the fast subset), the nightly schedule runs `full` (every Workbench file), and `workflow_dispatch` can pick either. The split is based on a measured run rather than taste — `full` buys 8 more real passes for ~523s more test time, which is worth a nightly but not a merge gate. Skip reasons do **not** appear in the log even with `-rs`, because VIP's plugin owns the terminal reporter; read them from `<skipped message=...>` in the uploaded `smoke-results.xml`.
    The three cross-cutting suites (`cross_product/test_resources`, `security/test_auth_policy`, `config_hygiene/test_secrets`) run in all three product workflows. `test_secrets` asserts no plaintext `api_key`/`password` in the generated `vip.toml`, so credentials must be passed to pytest as step `env` (`VIP_CONNECT_API_KEY`, `VIP_TEST_PASSWORD`) and never written into the config file.
-   **`add-to-team-project.yml`** -- when a `team: connect`, `team: workbench`, or `team: package manager` label is added to an issue, adds it to that product team's org-level GitHub project board. Ported from rstudio/helm. Requires the cross-org `POSIT_PLATFORM_CLIENT_ID`/`POSIT_PLATFORM_PEM` app secrets.
-   **`weekly-summary.yml`** -- Mondays (and on demand via `workflow_dispatch`) gathers the week's merged PRs, has Claude pick the highlights via Bedrock, and posts a Slack summary; `pull_request` runs are a dry run that builds and logs the payload without posting. Requires the `SLACK_WEBHOOK_VIP_WEEKLY_SUMMARY` secret and permission to assume the `gha-claude-code` AWS role (account `935931255537`). That role's OIDC trust is generated entirely from the `repositories` list in `pulumi/aws/account/aws-platform-team/aws_platform_team/iam.py` in `posit-dev/platform-infra`, so `posit-dev/vip` has to be listed there.

## PR titles

PR titles must use conventional commit format. CI enforces this via `.github/workflows/pr-title.yml`. Squash merges use the PR title as the commit message, so the title directly becomes the git history.

For Copilot-authored PRs, set the PR title to conventional format before requesting review. If the generated title is not conventional, rename it immediately instead of waiting for CI feedback.

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

## Pytest warning filters

Register warning filters in `src/vip/plugin.py::pytest_configure` (via `config.addinivalue_line("filterwarnings", ...)`), not in `pyproject.toml`'s `[tool.pytest.ini_options]`. Filters in `pyproject.toml` only apply when pytest runs from this repo's rootdir -- users who install vip into another project pick up the plugin but not the config, so the warnings reappear there. Keeping the filters in the plugin means they travel with the installed package.

## Common mistakes to avoid

-   Forgetting to include `examples/` in ruff check paths.
-   Using `Markdown()` without `display()` in Quarto `.qmd` files.
-   Changing ruff version locally without updating the pinned version in `ci.yml`.
-   Adding product SDK imports (use httpx directly).
-   Writing tests that modify or delete existing customer content.
-   Adding a Workbench scenario that ends the shared auth session (sign-out, session revocation, password change) without ordering it last *and* restoring the session afterwards. Under `--interactive-auth` / `--headless-auth` every Workbench scenario shares one account, so ending that session breaks every scenario still running on other xdist workers, plus the cached auth session on disk. `test_workbench_signout` is the worked example.
-   Creating `.py` step files without a matching `.feature` file (or vice versa).
-   Forgetting the `@connect`/`@workbench`/`@package_manager` tag in feature files (breaks auto-skip).
-   Using non-conventional PR titles (must be `type: description`).
-   Relying on multi-line formatting to shorten lines -- `ruff format` will collapse list comprehensions back to one line if they fit within 100 chars. Extract a helper function instead.
-   Importing a pytest-bdd step module (anything under `src/vip_tests/**` that calls `@scenario` / `scenarios()`) from inside a selftest. `@scenario` inspects the caller's frame at import time, so importing it mid-test raises `IndexError: list index out of range` — and only under some orderings, so it passes locally and fails in CI under `pytest-randomly`. Put the helper you want to test in `conftest.py` and import it from there, or assert via `--collect-only` in a subprocess the way `selftests/test_workbench_ordering.py` does.
-   Running selftests with `-p no:randomly`. CI runs them randomized; disabling the plugin hides exactly the order-dependent failures it exists to catch.
-   Bypassing `vip install` with raw `uv run playwright install --with-deps chromium` (or `playwright install chromium`) in setup recipes, Dockerfiles, CI workflows, or docs. The whole `vip uninstall` reversibility relies on the `.vip-install.json` manifest that only `vip install` writes -- a raw `playwright install` leaves no record. The only acceptable alternative is `uv run vip install --skip-system` (used by CI workflows where the runner already has system libs), which still records the Playwright cache.
