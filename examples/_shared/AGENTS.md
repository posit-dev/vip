# Writing a VIP test extension

You are being asked to write a VIP test extension. Here is the contract.

VIP (Verified Installation of Posit) is a pytest-bdd test suite that
validates a deployment of Posit Connect, Workbench, and/or Package Manager.
An extension is a directory of `.feature`/`.py` pairs that VIP loads
alongside its own built-in tests. This document is a reference, not a
tutorial -- read the scenario file(s) already in this directory for a worked
example, and come back here when you need to know what a fixture returns or
whether a marker exists.

## How an extension is loaded

```bash
vip verify --config vip.toml --extensions /path/to/this/directory
```

or, in `vip.toml`:

```toml
[general]
extension_dirs = ["/path/to/this/directory"]
```

Either way, every `.py` file in the directory is collected by pytest and
gets full access to VIP's fixtures and plugin behavior (auto-skip,
`min_version` gating, JSON/JUnit/SARIF reporting).

## Four-layer architecture

VIP (and every extension) is structured in four layers, each one only
talking to the layer directly below it (see `docs/test-architecture.md` for
the full guide):

1. **Test** -- `.feature` files (Gherkin scenarios). Business language only;
   no URLs, status codes, or selectors.
2. **DSL** -- step definitions (`given`/`when`/`then` functions) + fixtures,
   via `pytest-bdd`. Thin: push logic down to layer 3.
3. **Driver Port** -- client interfaces (`src/vip/clients/`) or Playwright
   page objects. This is what a step definition calls.
4. **Driver Adapter** -- `httpx` (API calls) or Playwright (browser
   automation). The actual wire/DOM traffic.

## The auto-skip contract

Every scenario must carry a product marker: `@pytest.mark.connect`,
`@pytest.mark.workbench`, or `@pytest.mark.package_manager`, applied
**directly on the `@scenario` function** in the `.py` file. VIP's plugin
(`src/vip/plugin.py`) reads these pytest markers during collection and
deselects (not skips -- removes from the run entirely) any test whose
product is not configured in `vip.toml`.

A `.feature` file can carry the matching Gherkin tag (`@connect` above a
`Scenario:` block) too, and pytest-bdd does turn that into the same pytest
marker -- but only for that one scenario. Tagging the whole `Feature:` block
applies the tag to every scenario in the file, which causes wrong
deselection when a file mixes products. **Omitting the marker entirely is
the single most common mistake**: the scenario then runs unconditionally,
against whatever client fixture happens to be available (or `None`), instead
of being cleanly excluded when its product isn't configured.

## Version gating

Use `@pytest.mark.min_version(product="connect", version="2024.09.0")` on a
`@scenario` function to skip a scenario when the deployed product version is
below the given one. `product` is one of `connect`, `workbench`,
`package_manager`. When the deployed version can't be determined, the test
is skipped and flagged N/A-by-version rather than run optimistically.

## Public fixtures (from VIP core)

All fixtures below are defined in `src/vip/fixtures.py`, which VIP registers
as a pytest plugin, so they are available to your extension wherever it lives
on disk -- do not redefine them in your own `conftest.py`, or you will
silently shadow the config-driven values.

One gap to know about: the Connect content-cleanup fixtures stay scoped to
VIP's own test package, so an extension that creates Connect content is
responsible for removing it (`connect_client.cleanup_content(guids)`).

| Fixture | Returns | Purpose |
|---|---|---|
| `vip_config` | `VIPConfig` | The full loaded `vip.toml` configuration. |
| `vip_verbose` | `bool` | Whether `--vip-verbose` was passed. |
| `connect_client` | `ConnectClient \| None` | Authenticated httpx client for the Connect API. `None` when Connect is not configured. |
| `connect_url` | `str` | Resolved Connect base URL (scheme-checked). |
| `workbench_client` | `WorkbenchClient \| None` | Authenticated httpx client for the Workbench API. `None` when Workbench is not configured. |
| `workbench_url` | `str` | Resolved Workbench base URL. |
| `kubernetes_client` | `KubernetesClient \| None` | Read-only Kubernetes client for session-capacity probes. `None` when Kubernetes is not configured. |
| `pm_client` | `PackageManagerClient \| None` | Authenticated httpx client for the Package Manager API. `None` when Package Manager is not configured. |
| `pm_url` | `str` | Resolved Package Manager base URL. |
| `interactive_auth` | `bool` | Whether `--interactive-auth`/`--headless-auth` established a browser session. |
| `auth_mode` | `str` | `"interactive"`, `"headless"`, or `"none"`. |
| `workbench_auth_error` | `str \| None` | Why pre-test Workbench auth did not complete, if it didn't. |
| `test_username` | `str` | Configured test account username. |
| `test_password` | `str` | Configured test account password. |
| `auth_provider` | `str` | e.g. `"password"`, `"saml"`, `"oidc"`, `"oauth2"`. |
| `expected_r_versions` | `list[str]` | R versions from `vip.toml`'s `[runtimes]` block. |
| `expected_python_versions` | `list[str]` | Python versions from `vip.toml`'s `[runtimes]` block. |
| `performance_config` | `PerformanceConfig` | The `[performance]` config block. |
| `data_sources` | `list[DataSourceEntry]` | Configured data sources. |
| `email_enabled` | `bool` | Whether email is enabled in the deployment config. |
| `chronicle_enabled` | `bool` | Whether Chronicle is enabled in the deployment config. |
| `browser_type_launch_args` | `dict` | Playwright launch-args override that applies VIP's proxy config. Internal plumbing -- request it only if you need to further customize browser launch, not as a general-purpose Playwright fixture. |
| `browser_context_args` | `dict` | Playwright context-args override that injects the shared auth storage state and TLS settings. Same caveat as above. |

**`connect_client`, `workbench_client`, `pm_client`, and `kubernetes_client`
can all be `None`.** Guard against that (skip or assert) before using one,
the same way VIP's own tests do.

## Shared Gherkin steps

VIP registers these `Given` steps globally, so a `.feature` file in your
extension can use them without you writing a step definition. Each one skips
the scenario when that product is absent from `vip.toml`, which is a useful
complement to the product marker: the marker decides whether the scenario is
collected at all, the step decides whether it runs.

| Step | Defined in |
|---|---|
| `Given Connect is configured in vip.toml` | `src/vip/fixtures.py` |
| `Given Workbench is configured in vip.toml` | `src/vip/fixtures.py` |
| `Given Package Manager is configured in vip.toml` | `src/vip/fixtures.py` |

Every other step in your `.feature` files is yours to define.

## Registered markers

Registered in `src/vip/plugin.py` (`pytest_configure`):

| Marker | Meaning |
|---|---|
| `connect` | Test for Posit Connect. Drives auto-skip. |
| `workbench` | Test for Posit Workbench. Drives auto-skip. |
| `package_manager` | Test for Posit Package Manager. Drives auto-skip. |
| `prerequisites` | Prerequisite check; VIP runs these before everything else. |
| `cross_product` | Cross-product / admin test. |
| `performance` | Performance validation test (opt-in; excluded by default). |
| `security` | Security validation test. |
| `config_hygiene` | Check of VIP's own configuration (opt-in; excluded by default). |
| `slow` | Detailed/long-running check; excluded by `vip verify --basic`. |
| `min_version(product, version)` | Skip when `product` is below `version`. |
| `if_applicable` | Skip when the related feature is not configured. |
| `api_auth` | Test requires only an API key, not browser credentials (relevant under `--api-auth`/`--no-auth`). |
| `rstudio` | Workbench RStudio IDE scenario. |
| `vscode` | Workbench VS Code IDE scenario. |
| `jupyter` | Workbench JupyterLab IDE scenario. |
| `positron` | Workbench Positron IDE scenario. |

## Client entry points (`src/vip/clients/`)

These are the classes behind the `*_client` fixtures above -- reach for
them through the fixtures rather than constructing your own.

| Class | Module | Purpose |
|---|---|---|
| `BaseClient` | `src/vip/clients/base.py` | Shared base for all HTTP clients: proxy-aware httpx transport, TLS (`insecure`/`ca_bundle`), auth header or `httpx.Auth`, scaled timeouts. |
| `ConnectClient` | `src/vip/clients/connect.py` | httpx wrapper for the Connect API. |
| `WorkbenchClient` | `src/vip/clients/workbench.py` | httpx wrapper for the Workbench API; also has session-ownership helpers (`is_vip_session`, `session_owner`) used by cleanup code. |
| `PackageManagerClient` | `src/vip/clients/packagemanager.py` | httpx wrapper for the Package Manager API. |
| `KubernetesClient` | `src/vip/clients/kubernetes.py` | Read-only Kubernetes wrapper for cluster/session capacity probes. |
| `terminal_run` | `src/vip_tests/workbench/exec.py` | Helper (not a client class) that runs a shell command inside a live Workbench IDE terminal via Playwright and returns its captured output. Used for in-session package-install checks; see `examples/cross_product_validation/test_gxp_validation.py`. |

## Rules

- Use `pytest-bdd`: `@scenario`, `@given`, `@when`, `@then`.
- Mirror scenario names exactly between the `.feature` file and the
  `@scenario(...)` call in the `.py` file -- pytest-bdd matches on the
  literal string.
- Apply the product marker (`@pytest.mark.connect`, etc.) directly on every
  `@scenario` function, not only as a Gherkin tag.
- Prefer VIP's fixtures (`connect_client`, `connect_url`, ...) over
  constructing your own HTTP client or reading `vip.toml` by hand.
- Do not hardcode URLs or credentials. Read them from `vip_config` or the
  narrower fixtures above so the extension checks whatever deployment the
  user configured, not a fixed address.
- Use `target_fixture=` to pass state from a `when` step to a `then` step,
  not a module-level global.

## Worked example (minimal shape)

```gherkin
# my_check.feature
Feature: My check
  @connect
  Scenario: My endpoint responds successfully
    Given I have my endpoint to verify
    When I request my endpoint
    Then it responds successfully
```

```python
# my_check.py
import httpx
import pytest
from pytest_bdd import given, scenario, then, when


@pytest.mark.connect
@scenario("my_check.feature", "My endpoint responds successfully")
def test_my_check():
    pass


@given("I have my endpoint to verify")
def have_endpoint():
    pass


@when("I request my endpoint", target_fixture="response")
def request_endpoint(connect_url):
    return httpx.get(f"{connect_url}/__api__/server_settings", timeout=15)


@then("it responds successfully")
def responds_ok(response):
    assert response.status_code < 400
```
