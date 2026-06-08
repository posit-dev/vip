# Plan for issue #298: add example of adding a custom test extension

## Context

Customers extending VIP for GxP deployments or other regulated environments need to verify specific R and Python versions are available across Workbench and Connect. While VIP already supports loading external test directories via `--extensions` or `extension_dirs` in `vip.toml`, the current `examples/custom_tests/` example is minimal — it demonstrates only a simple HTTP health check, not the cross-product runtime verification pattern that GxP users need.

The issue author requests a complete working example that verifies:
- Specific R and Python versions are available in both Workbench and Connect

**Scope clarification on package verification:**
The current VIP client APIs support **version listing only**:
- `ConnectClient.r_versions()` / `.python_versions()` — returns list of available runtime versions
- `WorkbenchClient` — has no package/runtime surface (blocked on session-exec primitive in #301)

Real package-install verification requires the deploy-a-bundle-and-scrape-logs flow demonstrated in `src/vip_tests/connect/test_packages.py`. The scaffolded example will focus on **runtime version checks** with inline comments pointing users to `connect/test_packages.py` for the deeper install-verification pattern. Full cross-product package validation depends on the Workbench session-exec feature tracked in #301 (plan PR #317).

The preferred implementation is a `vip scaffold` or `vip init-extension` subcommand that generates a ready-to-run custom test directory with this pattern baked in. The alternative is documentation-only, but that requires users to copy-paste significant boilerplate.

## Architecture

This lands in two places:

1. **`src/vip/cli.py`** — add a new `scaffold` subcommand that writes the example test files to a user-specified directory
   - Initial implementation: defaults to copying `examples/cross_product_validation/`
   - Future extensibility: can add `--template` option to select from multiple examples (e.g., `--template http_health_check` or `--template cross_product_validation`)
2. **`examples/cross_product_validation/`** — a reference implementation directory containing:
   - `.feature` file describing runtime version verification scenarios
     - **Must include `@connect @workbench` tags** for auto-skip behavior when only one product is configured
   - `.py` step definition file that uses existing VIP fixtures (`workbench_client`, `connect_client`, `expected_r_versions`, `expected_python_versions`)
   - `conftest.py` with fixtures for expected runtime versions, wired to sensible defaults or `vip.toml`
     - Example defaults: `required_r_versions = ["4.4.0", "4.3.3"]`, `required_python_versions = ["3.12.0", "3.11.0"]`
   - `README.md` — explains the example, how to customize it, and points to `src/vip_tests/connect/test_packages.py` for package-install verification patterns

The `scaffold` command copies the reference directory to the user's target path and optionally templates in their specific version and package requirements.

## Components

**New files:**
- `examples/cross_product_validation/test_runtime_validation.feature` — Gherkin scenarios for runtime version checks
  - **Must include `@connect @workbench` auto-skip tags** at the feature level
- `examples/cross_product_validation/test_runtime_validation.py` — step definitions using VIP's client fixtures
  - Uses `connect_client.r_versions()` / `.python_versions()` for Connect version queries
  - Includes inline comments pointing to `src/vip_tests/connect/test_packages.py` for package-install verification patterns
  - Acknowledges Workbench package verification is blocked on #301 (plan PR #317)
- `examples/cross_product_validation/conftest.py` — fixtures for expected runtime versions with sensible defaults
  - Example: `@pytest.fixture def required_r_versions(): return ["4.4.0", "4.3.3"]`
  - Example: `@pytest.fixture def required_python_versions(): return ["3.12.0", "3.11.0"]`
  - Or wired to `vip.toml` via `vip_config` fixture: `vip_config.runtimes.r_versions`
- `examples/cross_product_validation/README.md` — explains the example, how to customize fixtures, and references deeper patterns

**Optionally renamed files:**
- Defer to follow-up: `examples/custom_tests/` → `examples/http_health_check/` (see Open Questions below)

**Modified files:**
- `src/vip/cli.py` — add `scaffold` subcommand and handler function `run_scaffold(args)`

**Out of tree (user-facing):**
When a user runs `vip scaffold --output ./my-custom-tests`, the tool writes the example files from `examples/cross_product_validation/` to `./my-custom-tests/`, ready to run with:
```bash
vip verify --config vip.toml --extensions ./my-custom-tests
```

## Verification

1. Selftest coverage:
   - `selftests/test_cli.py` — add a test that invokes `run_scaffold()` or the CLI entry with a temp output directory
   - **Assert on scaffolded content**, not just file existence:
     - `.feature` file carries `@connect @workbench` tags for auto-skip
     - `.py` step file imports from `pytest_bdd` (`from pytest_bdd import scenario, given, when, then`)
     - `conftest.py` defines the required fixtures (`required_r_versions`, `required_python_versions`)
   - Use `pytester` or `tmp_path` fixture to isolate the test

2. Manual verification (demo):
   ```bash
   uv run vip scaffold --output /tmp/cross-product-tests
   ls /tmp/cross-product-tests
   # Should contain: test_runtime_validation.feature, test_runtime_validation.py, conftest.py, README.md
   
   uv run vip verify --connect-url https://demo.connect --workbench-url https://demo.workbench \
     --extensions /tmp/cross-product-tests --collect-only
   # Should discover the new custom test scenarios and respect auto-skip tags
   ```

3. Linting and checks:
   ```bash
   just check
   # Equivalent to:
   # uv run ruff check src/ selftests/ examples/
   # uv run ruff format --check src/ selftests/ examples/
   ```
   
   Ensure `examples/` remains in the ruff paths per `CLAUDE.md` and the `justfile` recipe.

## Open questions

- **UNCONFIRMED:** Should the `scaffold` command template in version/package requirements interactively (prompt the user), or simply copy the files and expect the user to edit `conftest.py` afterward?
  - **Leaning toward:** simple file copy + README instructions. Interactive templating adds complexity and most users will want to hand-edit their requirements anyway.

- **CONFIRMED:** Should the example test directory be named `examples/gxp_validation/` or something more generic like `examples/cross_product_validation/`?
  - **Decision:** `examples/cross_product_validation/` because the pattern applies beyond GxP (any customer who needs to lock runtime/package versions).

- **CONFIRMED:** Should the scaffold command default to copying from `examples/cross_product_validation/` or should it be extensible (multiple scaffold templates)?
  - **Decision:** single template for now; extensibility can be added later if demand emerges.

- **DEFERRED:** Should we rename `examples/custom_tests/` to something more descriptive like `examples/http_health_check/` for consistency with `examples/cross_product_validation/`?
  - **Concern raised:** having one folder named `custom_tests` while another is named `cross_product_validation` creates inconsistency
  - **Potential future examples:** 
    - `examples/http_health_check/` (current `custom_tests/`) — basic HTTP connectivity verification
    - `examples/cross_product_validation/` — runtime/package version validation across products
    - `examples/ssl_certificate_validation/` — verifying SSL certificates are valid and not expiring soon
    - `examples/api_response_time/` — performance benchmarking for API endpoints
    - `examples/user_provisioning/` — testing user/group sync from LDAP/SAML
  - **Decision:** Defer rename to a follow-up issue/PR. Renaming requires updating inline path references in docstrings/comments (`extension_dirs = ["/path/to/custom_tests"]`) inside the moved files. This plan focuses on the scaffolding feature; the rename can be addressed separately once the multi-template pattern is proven.

## Out of scope

- Generating the `vip.toml` configuration file itself (users can already run `cp vip.toml.example vip.toml`).
- Full package-install verification across both products (requires Workbench session-exec primitive tracked in #301 / plan PR #317; Connect pattern exists in `src/vip_tests/connect/test_packages.py` but is too complex for a minimal scaffold).
- Integration with the Shiny app UI to invoke the scaffold command (the Shiny app is for running tests, not generating them).
- CI workflow changes (this is a documentation and CLI usability enhancement, not a test suite change).
- Renaming `examples/custom_tests/` → `examples/http_health_check/` (deferred to follow-up to keep this PR focused on scaffolding; see Open Questions).
