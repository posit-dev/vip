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
-   Say what a skip *means*. `vip.attest.not_applicable(reason)` says there was nothing to check here (product not configured, tier lacks the feature) and keeps the run green. `vip.attest.unproven(reason)` says VIP was asked to check something and could not, which fails the run with exit code 6 unless `--allow-unproven` is passed. A bare `pytest.skip()` still behaves like `not_applicable`; prefer the explicit helper so the next reader does not have to infer which one you meant.

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
| `src/vip/attest.py` | The two skip helpers (`not_applicable`, `unproven`) that record whether a skipped check was out of scope or simply never verified |
| `src/vip/plugin.py` | pytest plugin: markers (including `slow`, used by `verify --basic`), auto-skip, JSON report output; `pytest_configure` also registers `vip.fixtures` as its own named plugin (`"vip-fixtures"`) so core fixtures resolve regardless of directory ancestry — see that module's docstring |
| `src/vip/fixtures.py` | VIP's core pytest fixtures and shared BDD "Given" steps (`vip_config`, `connect_client`, `browser_context_args`, etc.), registered by `vip.plugin.pytest_configure` rather than defined in a `conftest.py` — pytest scopes `conftest.py` fixtures by directory ancestry, which made them invisible to extension directories (issue #609) |
| `src/vip/version.py` | `ProductVersion` parsing/comparison for `min_version` gating; `MINIMUM_SUPPORTED_POSIT_TEAM` support floor (powers `vip version`) |
| `src/vip/workbench_ui.py` | Browser-driven Workbench session-cleanup sweep (`quit_vip_sessions_via_ui`), shared by the per-test cleanup fixture and `vip cleanup --workbench-url`; takes an `owner` so a per-test sweep only quits its own xdist worker's sessions |
| `src/vip/reporting.py` | Report data model for Quarto templates |
| `src/vip/report_content.py` | Format-neutral report content shared by both rendering backends: titles, outcome/badge styling (colors drift-guarded against `styles.css` by `selftests/test_report_content.py`), grouping, skip wording, provenance rows |
| `src/vip/report_html.py` | HTML backend: renders `report_content` into the fragments `index.qmd`/`details.qmd` display |
| `src/vip/report_typst.py` | Typst backend: renders the same content as Typst markup for `report/vip-report.qmd` → `_output/vip-report.pdf`; every dynamic value passes through `_lit` (Typst-injection escaping) |
| `src/vip/clients/connect.py` | httpx client for Connect API |
| `src/vip/clients/workbench.py` | httpx client for Workbench API; `quit_vip_sessions` warns loudly (not silently) when a VIP session persists after all retries. `session_owner` / `is_vip_session_for_owner` decide whether a VIP session belongs to the sweeping worker — see "Session ownership" below |
| `src/vip/clients/packagemanager.py` | httpx client for Package Manager API |
| `src/vip/install/platform.py` | Distro detection (rhel/debian/macos) + canonical Chromium package lists |
| `src/vip/install/manifest.py` | `.vip-install.json` read/write (atomic), schema gate, pending-package helpers |
| `src/vip/install/packages.py` | `rpm -q` / `dpkg-query` wrappers for pre-existing detection |
| `src/vip/install/playwright.py` | Playwright cache detection + `playwright install chromium` wrapper |
| `src/vip/install/plan.py` | Pure `build_install_plan` / `build_uninstall_plan` builders |
| `src/vip/install/runner.py` | Plan executor: dry-run formatting + execute (system packages, Playwright, manifest writes) |
| `src/vip_tests/conftest.py` | Directory-scoped warning filter (kept out of the global plugin deliberately) plus the three autouse Connect content-cleanup fixtures — see that file's docstring for why those stay directory-scoped instead of moving to `src/vip/fixtures.py` |
| `report/index.qmd` | Quarto summary page |
| `report/details.qmd` | Quarto detailed results page |
| `report/vip-report.qmd` | Quarto/Typst PDF edition (summary + full listing in one archivable file) |

## Extension examples

VIP ships two canonical extension examples in `examples/`:

| Directory | Purpose |
|---|---|
| `examples/custom_tests/` | Minimal HTTP health-check extension (simpler starting point) |
| `examples/cross_product_validation/` | GxP/regulated-environment pattern: runtime version checks + DESeq2/PyDeSEQ2 package installability across Connect and Workbench |

Generate either one in a new directory with `vip scaffold` (`--template` defaults to
`cross-product`, so bare `vip scaffold --output DIR` is unchanged):

```bash
vip scaffold --list
vip scaffold --template minimal --output ./my-custom-tests
vip scaffold --template cross-product --output ./my-custom-tests
```

Every scaffolded directory also gets an `AGENTS.md`, generated from the single shared source
`examples/_shared/AGENTS.md`. It's the extension contract for whoever (human or agent) writes the
new tests: the auto-skip rules, `min_version` gating, and an enumerated inventory of public
fixtures, registered markers, and client entry points. `selftests/test_scaffold_agents_md.py`
parses the real source and fails if that inventory ever drifts -- keep it in sync when fixtures or
markers change.

When writing a new extension example, follow the same four-layer architecture and add
`@pytest.mark.connect` / `@pytest.mark.workbench` decorators to every `@scenario` function so
auto-skip works correctly (feature-level Gherkin tags alone are not sufficient).

## Fixtures available in product tests

These are defined in `src/vip/fixtures.py` and registered as part of VIP's own pytest plugin
(`vip.plugin.pytest_configure`), so they are available to every test collected in a run —
including extension directories loaded via `--vip-extensions`, not just tests under
`src/vip_tests`:

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

Because the promotion fires with no flag set, it announces itself on stderr once per process (`_promotion_notice_emitted` guards the repeat — `build_proxy_map` runs once per client construction and once per `proxy_for_url` caller). The notice names the gateway (userinfo redacted) and both escape hatches. Don't drop it: the user this hits hardest never asked for proxy support at all — they have a stray `http_proxy` exported for `dnf`/`apt`, their products were reachable directly, and without the notice the only symptom is "curl works, VIP doesn't" with nothing pointing at the promotion. Covered by `test_http_proxy_promotion_announces_itself_once` and friends in `selftests/test_proxy.py`.

The promotion has two knock-on effects, both ratified rather than special-cased — don't "fix" either without reading this:

- It engages the scheme-downgrade guard for an operator who never named an https proxy. `applicable_proxy` becomes non-`None` for every inferred-https URL, so `resolve_url_scheme` stops downgrading (see the bullet below). Concretely: `vip verify --connect-url connect.example.com` against an http-only product downgraded and worked before proxy support, and now keeps `https://` and fails loudly on any host with `http_proxy` exported. That is the safe direction, and both mitigations are one step — pass an explicit scheme, or list the host in `NO_PROXY`. Locked in by `test_lone_http_proxy_env_guards_downgrade_through_promotion` and `test_lone_http_proxy_with_no_proxy_host_downgrades_again` in `selftests/test_scheme_resolution_proxy.py`; the pre-existing `test_env_proxy_also_guards_downgrade` sets `https_proxy` and does *not* cover this path.
- It splits VIP from the env-only paths listed under "Deliberately scoped out" below. Those use bare `httpx.get` with `trust_env=True`, which does not promote, so with a lone `http_proxy` the API clients tunnel https through the gateway while `prerequisites/test_components.py` and friends send the same https URL direct. The reachability probes can therefore fail while the client tests pass, on exactly the proxy-only network promotion exists to serve. Wiring those paths to `vip.proxy` is the real fix; until then this is a known asymmetry, not a mystery.

Four Chromium-specific edges to keep in mind when touching `playwright_proxy`:
- **A bare `NO_PROXY` host needs two Chromium bypass entries.** httpx renders `NO_PROXY=example.com` as `all://*example.com` → `^(.+\.)?example\.com$`: the apex and dot-separated subdomains, but *not* `badexample.com`. Chromium has no single pattern with that match set — bare `example.com` is exact-host only (too narrow: the browser proxies subdomains httpx reaches directly), and `*example.com` is a plain glob that also swallows `badexample.com` (too wide: the browser goes direct where httpx proxies). `_pattern_to_bypass_hosts` therefore emits `example.com,*.example.com`. Leading-dot (`all://*.foo`) and literal-host patterns stay one entry. If you touch this, re-check both directions — the negative half is what the parametrized parity test in `selftests/test_proxy.py` exists for.
- A scheme-qualified pattern keeps its scheme, and an unmatchable host emits nothing. httpx uses a `NO_PROXY` host containing `://` verbatim, so `https://example.com` bypasses https and still proxies http to the same host; Chromium's grammar is `[SCHEME://]HOSTNAME_PATTERN[:PORT]`, so a scheme-less entry bypasses both. `_pattern_to_bypass_hosts` partitions the scheme off and re-attaches it to every entry — the same reason `_bypass_host_for_url` qualifies its fallback entry. It also emits nothing when a `*` or a leading `.` survives into the literal domain, because httpx's `URLPattern` only special-cases a host starting with `*`: `*.foo.com` and `https://.foo.com` both compile to regexes no real hostname matches, while Chromium would happily glob them and send the browser direct where every httpx call is proxied. A whole-scheme wildcard *does* render — `https://*` means "bypass all https" to both httpx and Chromium — but only once something narrows it. A bare `all://*` ties with the catch-all `all://` on `URLPattern.priority` and loses under stable sorting, so httpx proxies it and a bare Chromium `*` would bypass everything in the browser alone; a scheme or a port breaks the tie (`all://*:8443` sorts first and does bypass).
- Ports come from `URLPattern`, never from the pattern text. httpx resolves a port against the pattern's own scheme and normalises a default one away, so `https://foo:443` matches https to `foo` on *any* port and has to render port-less — forwarding the literal `:443` restricts Chromium to that one port. The two models genuinely disagree in one place: httpx compares against a URL's *normalised* port (a default port is `None`) while Chromium compares against the *effective* port, so an `all://` pattern carrying 80 or 443 keeps it (that scheme has no default) and then matches only the scheme for which the port is *not* default — `all://*host:443` matches `http://host:443` and never `https://host`. A scheme-less Chromium `host:443` matches implicit-port https too, so `_OTHER_SCHEME_FOR_PORT` qualifies those entries with the opposite scheme. This is why the function derives scheme/host/port from `URLPattern` rather than slicing the string: hand-parsing produced three separate divergences here, each found a review round apart.
- **`--proxy`/`--no-proxy` only reach the generated temp config.** Any run that loads a config file — `--config` *or* the default `./vip.toml` — has no consumer for them, so `run_verify` warns. Key that warning on "no temp config was generated", not on `config_path`, which is still `None` on the default-resolution path.

Three sharp edges the fix also closes:
- **A proxy scheme httpx cannot use** (`_proxy_transport` → `ProxyConfigError`): httpx rejects such a URL in two ways at two depths — `httpx.Proxy` raises `ValueError` for anything outside http/https/socks5, and `HTTPTransport` raises `ImportError` for `socks5://` when the optional `socksio` package is absent (VIP does not depend on `httpx[socks]`). `ALL_PROXY` is conventionally where a SOCKS proxy goes, and since `BaseClient` resolves its mounts in `__init__`, the bare httpx raise lands at *fixture setup* and errors every product test with a message naming neither the value nor the variable it came from. Before the clients honored the environment at all, such a variable was inert for them, so this is a regression the proxy work introduces. `build_mounts` re-raises with the redacted URL, where VIP read it, and the ways out — including that Chromium accepts `socks5://` and would proxy happily while httpx cannot, so an unresolved one is a browser/API split too.
- **Scheme downgrade** (`resolve_url_scheme`): a `ProxyError` must never trigger the `https://`→`http://` fallback (it says nothing about the origin's TLS), and when a proxy applies the raw-socket TLS-listener tiebreak is skipped entirely (it bypasses the proxy, so its "nothing is listening" verdict is about a path VIP will never take). Downgrading there would send credentials in cleartext on a proxy-only host. Note that "a proxy applies" includes a promoted lone `HTTP_PROXY`, which is what makes this guard fire far more often than the explicit-`[proxy]` case it was written for — see the promotion knock-on effects above.
- **retries**: httpx's `HTTPProxy` pool drops the `retries` value (only the direct `ConnectionPool` keeps it). Proxied requests therefore get no connection-retries; this matches httpx and is documented in `proxy.py`, not worked around.

If you add a new HTTP egress path, route it through `vip.proxy` — do not reintroduce a raw `httpx.get`/socket that bypasses the proxy.

**Deliberately scoped out (env-proxy only, not the explicit `[proxy]` config).** A few opt-in/diagnostic paths still use bare `httpx.get` with httpx's default `trust_env=True`, so they honor the ambient `HTTP(S)_PROXY`/`NO_PROXY` env but not an explicit `[proxy]` TOML/`--proxy` config: the test-layer probes in `src/vip_tests/**` (e.g. `prerequisites/test_components.py`, `performance/*`, `security/*`, `package_manager/*`, `cross_product/test_resources.py`, `helpers.py`) and the load/perf engine (`src/vip/load_engine.py`, gated behind the `performance` category). Separately, the raw-socket TLS probes — `cross_product/test_ssl.py`, `security/test_https.py`, and `_tls_listener_present` in `auth.py` — honor **neither** the env vars nor `[proxy]`: they are `socket.create_connection` calls testing the *plaintext/handshake* boundary, so there is no proxy for them to speak through and they will fail outright on a host with no direct route out. Don't describe the env vars as covering "every request"; they cover every *HTTP* request. The Kubernetes client (`clients/kubernetes.py`) uses the `kubernetes` SDK (urllib3), not httpx, and is out of scope. Two more commands are env-only for a structural reason rather than a scoping one: `vip install` never loads a config file at all, so the `playwright install chromium` download honors only the environment (a `[proxy]`-only user fails at setup, before ever reaching `vip verify` — say so in any proxy docs you touch), and `mint_connect_key` (`vip auth`) takes a bare `--url` with no config, so it passes `proxy=None` and reads the environment.

Wiring the scoped-out paths to the explicit `[proxy]` config would mean threading `ProxyConfig` into `PerformanceConfig` and every test helper — worth doing only if a deployment needs an explicit proxy that differs from the environment. They agree with the client paths whenever the env names an https or catch-all proxy, which is the common case. They do not agree under a lone `HTTP_PROXY`: `build_proxy_map` promotes it to cover https and these paths don't, so the clients tunnel https while these send it direct. Don't describe them as merely "consistent for the env-var case" — that holds for `HTTPS_PROXY`, not for the http-only env the promotion exists to serve.

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

Every render also produces `_output/vip-report.pdf` from `report/vip-report.qmd` -- a native Quarto/Typst document, deliberately not a browser print, because the report exists partly to show off Quarto. `vip report` renders each document with its own `quarto render <doc>` call so a Quarto older than 1.4 (no Typst) still hands over the HTML report and only warns about the PDF. It cannot reuse the HTML pages (pandoc drops `IPython.display.HTML` content to its repr when targeting Typst), so `src/vip/report_typst.py` renders the same `report_content` as Typst markup. Two invariants when touching it: every dynamic value must go through `_lit` (a `#`/`*`/`$` in test output is live Typst markup otherwise), and visual changes must land in `report_content`/`styles.css` in the same commit so the HTML and PDF editions stay identical -- `selftests/test_report_content.py` guards the colors. The faces (Source Sans 3, Source Code Pro; both OFL) are vendored in `report/fonts/` so renders match across laptops, CI, and air-gapped hosts; the font files are part of `_REPORT_TEMPLATE_FILES` and the pyproject force-include block, which `selftests/test_cli_report.py` keeps in sync.

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
-   Reaching for a bare `pytest.skip()` when the real situation is "I could not check this". That is the failure mode #616 exists to close: an unverified deployment reporting itself as a passing one. If the product was configured and you still could not run the check, use `vip.attest.unproven()`.
-   Using non-conventional PR titles (must be `type: description`).
-   Relying on multi-line formatting to shorten lines -- `ruff format` will collapse list comprehensions back to one line if they fit within 100 chars. Extract a helper function instead.
-   Importing a pytest-bdd step module (anything under `src/vip_tests/**` that calls `@scenario` / `scenarios()`) from inside a selftest. `@scenario` inspects the caller's frame at import time, so importing it mid-test raises `IndexError: list index out of range` — and only under some orderings, so it passes locally and fails in CI under `pytest-randomly`. Put the helper you want to test in `conftest.py` and import it from there, or assert via `--collect-only` in a subprocess the way `selftests/test_workbench_ordering.py` does.
-   Running selftests with `-p no:randomly`. CI runs them randomized; disabling the plugin hides exactly the order-dependent failures it exists to catch.
-   Bypassing `vip install` with raw `uv run playwright install --with-deps chromium` (or `playwright install chromium`) in setup recipes, Dockerfiles, CI workflows, or docs. The whole `vip uninstall` reversibility relies on the `.vip-install.json` manifest that only `vip install` writes -- a raw `playwright install` leaves no record. The only acceptable alternative is `uv run vip install --skip-system` (used by CI workflows where the runner already has system libs), which still records the Playwright cache.
