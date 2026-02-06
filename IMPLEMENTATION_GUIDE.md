# VIP Implementation Guide

This document summarizes what has been built so far and describes how to go
about implementing and hardening the remaining tests.

## What exists today

### Project structure

```
vip/
├── src/vip/                     # Core library
│   ├── config.py                # TOML config loader + dataclasses
│   ├── plugin.py                # pytest plugin (markers, skip logic, JSON report)
│   ├── reporting.py             # Report data model for Quarto
│   └── clients/                 # Lightweight HTTP clients (httpx, no SDKs)
│       ├── connect.py           # Content CRUD, deploy, tags, runtime versions
│       ├── workbench.py         # Health, server info, sessions
│       └── packagemanager.py    # Repos, CRAN/PyPI availability
│
├── tests/                       # The VIP test suite (runs against real products)
│   ├── conftest.py              # Root fixtures: clients, auth, runtimes, data sources
│   ├── prerequisites/           # Server reachability, auth credentials present
│   ├── package_manager/         # CRAN/PyPI mirrors, repo listing, private repos
│   ├── connect/                 # Auth, content deploy, data sources, packages, email, runtimes
│   ├── workbench/               # Auth, IDE launch, sessions, packages, data sources, runtimes
│   ├── cross_product/           # SSL certs, monitoring, system resources
│   ├── performance/             # Load times, package speed, concurrency, resource usage
│   └── security/                # HTTPS enforcement, auth policy, secrets
│
├── selftests/                   # Framework tests (no products required, run in CI)
│   ├── test_config.py           # Config loading, TOML parsing, env vars
│   ├── test_plugin.py           # Version parsing, skip logic, JSON output, extensions
│   └── test_reporting.py        # Report data model, result loading
│
├── report/                      # Quarto report templates
│   ├── _quarto.yml              # Website config (cosmo theme, navbar)
│   ├── index.qmd                # Summary: pass/fail counts, category breakdown, failures
│   └── details.qmd              # Per-test listing with outcome and duration
│
├── examples/custom_tests/       # Extension example for customer-specific tests
├── .github/workflows/
│   ├── ci.yml                   # Lint + format + selftests (Python 3.10 & 3.12)
│   └── preview.yml              # Render Quarto report and publish PR preview to gh-pages
├── justfile                     # Task runner (setup, lint, test, selftest, report)
├── pyproject.toml               # Dependencies, markers, ruff config
└── vip.toml.example             # Configuration template
```

### Test inventory

Every test follows the same pattern: a `.feature` file with Gherkin scenarios
paired with a `.py` file containing step definitions.

| Category | File | Scenarios | Status |
|---|---|---|---|
| **Prerequisites** | `test_components` | Connect/Workbench/PM reachability | Implemented |
| | `test_auth_configured` | Credentials present | Implemented |
| **Package Manager** | `test_repos` | CRAN mirror, PyPI mirror, repo exists | Implemented |
| | `test_private_repos` | Private repos resolve | Implemented |
| **Connect** | `test_auth` | Web UI login, API key auth | Implemented |
| | `test_content_deploy` | Deploy Quarto, Plumber, Shiny, Dash | Implemented |
| | `test_data_sources` | External data source connectivity | Implemented |
| | `test_packages` | Package repo configured, PM URL in settings | Implemented |
| | `test_email` | Send test email | Implemented |
| | `test_runtime_versions` | R and Python versions match expected | Implemented |
| **Workbench** | `test_auth` | Web UI login | Implemented |
| | `test_ide_launch` | RStudio, VS Code, JupyterLab | Implemented |
| | `test_sessions` | Session starts and persists | Implemented |
| | `test_packages` | R repos.conf check | **Stub** |
| | `test_data_sources` | External data source connectivity | Implemented |
| | `test_runtime_versions` | R and Python versions match expected | Implemented |
| **Cross-product** | `test_ssl` | SSL cert valid, HTTP-to-HTTPS redirect | Implemented |
| | `test_monitoring` | Health endpoints respond | Implemented |
| | `test_resources` | Disk < 90%, memory > 10% available | Implemented |
| **Performance** | `test_login_load_times` | Page load < 10s per product | Implemented |
| | `test_package_install_speed` | CRAN/PyPI download < 30s | Implemented |
| | `test_concurrency` | 10 concurrent requests succeed, avg < 5s | Implemented |
| | `test_resource_usage` | Load avg and memory during traffic burst | Implemented |
| **Security** | `test_https` | HTTPS enforced, no version headers | Implemented |
| | `test_auth_policy` | Provider matches config, unauthed denied | Implemented |
| | `test_secrets` | No plaintext secrets in config, API key from env | Implemented |

**Selftests** (38 tests): config loading, plugin behavior (via pytester),
reporting module. All pass in CI.

### Key infrastructure

- **Auto-skip**: tests for unconfigured products are skipped automatically.
  The plugin reads `vip.toml` and checks each product's `enabled` flag and
  `url` field.
- **Version gating**: `@pytest.mark.min_version(product="connect", version="2024.05.0")`
  skips tests when the product is older than required.
- **Non-destructive cleanup**: Connect content created during tests is tagged
  with `_vip_test` and deleted in teardown.
- **Extensibility**: `--vip-extensions=/path/to/dir` adds a directory to
  pytest's collection at runtime.
- **Quarto report**: `pytest --vip-report=report/results.json` writes JSON
  that the Quarto templates read to render the HTML report.

---

## How to implement and harden the tests

### 1. Run the suite against a real deployment first

Before writing new tests, run the existing suite against an actual Posit Team
environment.  This will immediately surface:

- Selectors that don't match the real product UI (Playwright steps).
- API endpoints that have changed or return different shapes.
- Timing assumptions that are too tight or too loose.

```bash
cp vip.toml.example vip.toml
# Fill in real URLs, set env vars for secrets
pytest tests/ -v --vip-report=report/results.json 2>&1 | tee first-run.log
```

Start with prerequisites, then work outward:

```bash
pytest tests/prerequisites/ -v
pytest tests/connect/test_auth.py -v
pytest tests/connect/ -v
# ...
```

### 2. Harden Playwright selectors

The Workbench and Connect UI tests use CSS selectors that were written from
general knowledge of the products.  They will almost certainly need adjustment.
When fixing selectors:

- Use the Playwright codegen tool to discover the real selectors:
  ```bash
  playwright codegen https://your-connect-server.com
  ```
- Prefer `data-` attributes or `role` selectors over class names, which change
  between releases.
- Use multiple fallback selectors with commas:
  `page.fill("#username, [name='username'], [data-testid='username']", ...)`.
- When a selector varies by product version, consider parameterizing it through
  the config or using version-gated test variants.

### 3. Fill in stub tests

Two tests are stubs that need real implementations:

**`tests/workbench/test_packages.py` - R repos.conf check**

The current step `check_r_repos` returns the Workbench URL without verifying
anything.  To implement it:

- Option A (API): If the Workbench version exposes an admin API for repo
  configuration, query it and verify the Package Manager URL appears.
- Option B (UI): Use Playwright to navigate to the Workbench admin panel and
  inspect the repo configuration page.
- Option C (session): Start a session, run `getOption("repos")` in the R
  console, and verify the output contains the expected URL.

**`tests/security/test_secrets.py` - plaintext detection**

The current placeholder list (`{"...", "your-api-key", "changeme", ""}`) works
for basic cases.  To harden it:

- Use a regex that detects any `api_key = "..."` or `password = "..."` where
  the value looks like a real credential (length > 8, contains mixed chars).
- Consider checking for common secret patterns (base64 tokens, UUIDs, etc).

### 4. Add new test scenarios

When adding a new test:

1. **Create the feature file** in the appropriate category directory.  Follow
   the existing Gherkin style:

   ```gherkin
   @connect
   Feature: Connect content permissions
     As a Posit Team administrator
     I want to verify content permissions work correctly
     So that access controls are enforced

     Scenario: Published content respects viewer ACLs
       Given Connect is accessible at the configured URL
       When I publish a test content item
       And I set the access to specific users only
       Then unauthenticated requests to the content are denied
       And I clean up the test content
   ```

2. **Create the matching `.py` file** with step definitions:

   ```python
   from pytest_bdd import scenario, given, when, then

   @scenario("test_permissions.feature", "Published content respects viewer ACLs")
   def test_content_permissions():
       pass

   @given("Connect is accessible at the configured URL")
   def connect_accessible(connect_client):
       assert connect_client is not None

   # ... remaining steps
   ```

3. **Tag with the right marker** (`@connect`, `@workbench`, etc.) in the
   feature file header.  The plugin uses these to auto-skip when the product
   isn't configured.

4. **Clean up after yourself**.  Use `connect_client.delete_content(guid)` in
   a `then` step or a pytest fixture with `yield`/teardown.

5. **Add a selftest** if you're adding new framework behavior (config fields,
   plugin hooks, etc.).  Selftests go in `selftests/` and use pytester for
   plugin integration tests.

### 5. Add version-gated tests

When a feature only exists in certain product versions:

```python
@pytest.mark.min_version(product="connect", version="2024.09.0")
@scenario("test_new_api.feature", "New content type is supported")
def test_new_content_type():
    pass
```

The plugin compares the version from `vip.toml` (under `[connect] version`)
against the marker.  If the configured version is older, the test is skipped.
If no version is configured, the test runs optimistically.

### 6. Add diagnostic / misconfiguration tests

The test suite should help localize problems.  When you see a common support
issue, write a test that specifically checks for it.  Good candidates:

- **Load balancer sticky sessions**: Deploy content, hit it N times, verify
  the responses come from the same Connect process.
- **Proxy header forwarding**: Check that `X-Forwarded-For`,
  `X-Forwarded-Proto` headers are set correctly behind a reverse proxy.
- **DNS resolution**: Verify that product URLs resolve and that internal
  hostnames used by products (e.g., Connect reaching Package Manager) also
  resolve.
- **Clock skew**: Compare server time from each product's API against the
  local clock; large drift breaks SAML/OIDC.
- **File permissions**: On the host, verify that data directories have the
  correct ownership and permissions.

Place these in `cross_product/` with the `@cross_product` marker, or in
the relevant product directory.

### 7. Extend the API clients

The clients in `src/vip/clients/` are intentionally minimal.  Add methods as
needed for new tests.  Guidelines:

- Keep using plain `httpx` - avoid importing product SDKs.
- Return raw dicts from JSON responses rather than custom model objects.
- Add methods to the existing client classes rather than creating new ones.
- Don't worry about covering every API endpoint; only add what tests need.

Example:

```python
# In src/vip/clients/connect.py
def list_scheduled_reports(self) -> list[dict[str, Any]]:
    resp = self._client.get("/v1/schedules")
    resp.raise_for_status()
    return resp.json()
```

### 8. Write customer extension tests

Customer-specific tests go in a separate directory, not in the VIP source tree.
Point VIP at them via config or CLI:

```toml
# vip.toml
[general]
extension_dirs = ["/opt/acme-vip-tests"]
```

The extension directory should follow the same pattern: `.feature` +  `.py`
pairs.  A `conftest.py` in the directory can define customer-specific fixtures.
All VIP fixtures (`vip_config`, `connect_client`, etc.) are available
automatically.

See `examples/custom_tests/` for a working example.

### 9. Improve the Quarto report

The current report has two pages (summary and details).  Ideas for enhancement:

- **Timing charts**: Use plotly or matplotlib to visualize performance test
  durations over time (if results from multiple runs are available).
- **Diff view**: Compare two results.json files to show regressions.
- **Category detail pages**: One Quarto page per test category with deeper
  breakdowns.
- **Deployment topology**: Render a diagram of the product URLs and their
  connectivity status.

The report reads `report/results.json` (written by `--vip-report`).  The
Python code blocks in the `.qmd` files use only the standard library plus
`IPython.display.Markdown` for rendering.

### 10. CI and local development workflow

```bash
# One-time setup
just setup                        # uv sync + playwright install

# Development loop
just check                        # ruff lint + format check
just selftest                     # Run framework tests (fast, no products needed)
just selftest -- -k test_config   # Run a subset

# Against a real deployment
just test                         # All product tests
just test-product connect         # Just Connect
just test -- --vip-report=report/results.json  # With report

# Generate and view the report
just report
open report/_output/index.html
```

The CI pipeline runs on every PR:

- **ci.yml**: ruff lint/format + selftests on Python 3.10 and 3.12.
- **preview.yml**: runs selftests, renders the Quarto report, publishes a
  preview to `gh-pages` via `rossjrw/pr-preview-action`.  A comment with the
  preview URL is posted on the PR automatically.
