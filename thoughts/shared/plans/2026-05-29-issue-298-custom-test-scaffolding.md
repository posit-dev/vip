# Plan for issue #298: add example of adding a custom test extension

## Context

Customers extending VIP for GxP deployments or other regulated environments need to verify specific R and Python versions are available across Workbench and Connect, and that key packages (e.g. DESeq2, PyDeSEQ2) are installable. While VIP already supports loading external test directories via `--extensions` or `extension_dirs` in `vip.toml`, the current `examples/custom_tests/` example is minimal — it demonstrates only a simple HTTP health check, not the cross-product runtime verification pattern that GxP users need.

The issue author requests a complete working example that:
- Verifies specific R and Python versions are available in both Workbench and Connect
- Verifies that DESeq2 (R) and PyDeSEQ2 (Python) packages are installable — the core GxP value

**Relationship to built-in coverage (#303 / PR #327):**
PR #327 (in-flight as of this writing, implements #303) adds built-in Workbench runtime-version scenarios using `R_VERSION_DROPDOWN` / `PYTHON_VERSION_DROPDOWN` selectors from `src/vip_tests/workbench/pages/homepage.py` and step definitions in `src/vip_tests/workbench/test_runtime_versions.py`. That coverage handles the standard version-check path in the built-in test suite. The example here should **complement, not duplicate** it: the scaffold example demonstrates how an extension author wires up the same pattern outside the built-in suite, and adds the package-install scenario that #303 does not cover.

**Workbench package-install primitives (#301 / PR #349):**
PR #349 (merged) added `src/vip_tests/workbench/exec.py` with `terminal_run(page, cmd, timeout, *, readback_lang=...)`, `rstudio_eval`, and `read_file`. These make it feasible to verify package installation from within a live RStudio session. The scaffold example will include a Workbench-side install check using `terminal_run`.

The preferred implementation is a `vip scaffold` or `vip init-extension` subcommand that generates a ready-to-run custom test directory with this pattern baked in. The alternative is documentation-only, but that requires users to copy-paste significant boilerplate.

## Architecture

This lands in two places:

1. **`src/vip/cli.py`** — add a new `scaffold` subcommand that writes the example test files to a user-specified directory
   - Initial implementation: defaults to copying `examples/cross_product_validation/`
   - Future extensibility: can add `--template` option to select from multiple examples (e.g., `--template http_health_check` or `--template cross_product_validation`)
2. **`examples/cross_product_validation/`** — a reference implementation directory containing:
   - `.feature` file describing runtime version verification scenarios and package install scenarios
     - **Must include `@connect @workbench` tags** for auto-skip behavior when only one product is configured
   - `.py` step definition file that uses existing VIP fixtures (`workbench_client`, `connect_client`, `expected_r_versions`, `expected_python_versions`, `page`)
   - `conftest.py` with fixtures for expected runtime versions and package names, wired to sensible defaults or `vip.toml`
     - Reuses (or carefully overrides) the existing `expected_r_versions` / `expected_python_versions` fixtures from `src/vip_tests/conftest.py` — see the Components section for naming guidance
   - `README.md` — explains the example, how to customize it, and points to `src/vip_tests/connect/test_packages.py` and `src/vip_tests/workbench/test_packages.py` for deeper install-verification patterns

The `scaffold` command copies the reference directory to the user's target path and optionally templates in their specific version and package requirements.

## Components

**New files:**
- `examples/cross_product_validation/test_gxp_validation.feature` — Gherkin scenarios for runtime version checks and package install verification
  - **Must include `@connect @workbench` auto-skip tags** at the feature level
  - Scenarios:
    1. *Connect R versions match requirements* — checks `connect_client.r_versions()` against config
    2. *Connect Python versions match requirements* — checks `connect_client.python_versions()` against config
    3. *DESeq2 is installable on Connect* — deploys a minimal bundle that installs DESeq2, following the pattern in `src/vip_tests/connect/test_packages.py`; skippable via a fixture flag
    4. *PyDeSEQ2 is installable on Connect* — same pattern for PyDeSEQ2 (Python)
    5. *R package is installable in Workbench RStudio session* — uses `terminal_run` from `exec.py` to install DESeq2 in a live session; skippable via fixture flag
  - Note: Workbench runtime-version checks via the session dialog UI (using `R_VERSION_DROPDOWN` / `PYTHON_VERSION_DROPDOWN` selectors from `homepage.py`) are covered by the built-in suite (PR #327 / #303). The example intentionally does not duplicate that scenario; instead, the README points readers to `src/vip_tests/workbench/test_runtime_versions.py` once PR #327 lands.

- `examples/cross_product_validation/test_gxp_validation.py` — step definitions using VIP's client fixtures
  - Uses `connect_client.r_versions()` / `.python_versions()` for Connect version queries
  - Uses `terminal_run(page, "R -e 'install.packages(\"DESeq2\", repos=...)'")` from `exec.py` for Workbench install check
  - Package-install scenarios are conditionally skippable: `if not check_packages: pytest.skip("package install checks skipped")`
  - **Each `@scenario` test function must carry `@pytest.mark.connect` and/or `@pytest.mark.workbench` decorators.** The auto-skip logic in `src/vip/plugin.py` (`_should_deselect_for_product`) keys off pytest markers via `item.get_closest_marker()`. Gherkin feature-level `@connect @workbench` tags feed a secondary fallback path via `Given` step text matching; they are not sufficient on their own for extension tests that do not use `Given Connect is configured in vip.toml`. Applying `@pytest.mark.connect` / `@pytest.mark.workbench` directly on the scenario function is the reliable mechanism and mirrors every built-in VIP test. Example:
    ```python
    import pytest
    from pytest_bdd import scenario

    @pytest.mark.connect
    @scenario("test_gxp_validation.feature", "Connect R versions match requirements")
    def test_connect_r_versions():
        pass

    @pytest.mark.connect
    @pytest.mark.workbench
    @scenario("test_gxp_validation.feature", "R package is installable in Workbench RStudio session")
    def test_workbench_r_package():
        pass
    ```

- `examples/cross_product_validation/conftest.py` — fixtures for expected runtime versions and package check flags
  - **Important:** `src/vip_tests/conftest.py` already defines `expected_r_versions` and `expected_python_versions` as session-scoped fixtures wired to `vip_config.runtimes.r_versions` / `vip_config.runtimes.python_versions`. The example conftest MUST NOT redefine fixtures with the same names — that would silently shadow the config-driven fixtures in users who merge the example into an existing test suite.
  - **Recommended approach:** reuse the existing `expected_r_versions` and `expected_python_versions` fixtures by simply requesting them in step definitions. Add only the new fixtures the example needs:
    - `check_packages: bool` — defaults to `True`; set to `False` to skip slow install-verification scenarios
    - `r_package_name: str` — defaults to `"DESeq2"`
    - `python_package_name: str` — defaults to `"PyDeSEQ2"`
  - Alternatively, if the example needs standalone defaults without a `vip.toml` runtimes block, define fixtures under distinct names (e.g. `example_r_versions` / `example_python_versions`) and document the naming choice.

- `examples/cross_product_validation/README.md` — explains the example, how to customize fixtures, references deeper patterns in `src/vip_tests/connect/test_packages.py`, `src/vip_tests/workbench/test_packages.py`, and `src/vip_tests/workbench/exec.py`

**Optionally renamed files:**
- Defer to follow-up: `examples/custom_tests/` → `examples/http_health_check/` (see Open Questions below)

**Modified files:**
- `src/vip/cli.py` — add `scaffold` subcommand and handler function `run_scaffold(args)`
- `CLAUDE.md` — add a note under the examples/ section documenting the new `examples/cross_product_validation/` directory and the `vip scaffold` command, so future agents are aware of both
- `docs/test-architecture.md` — mention `examples/cross_product_validation/` as a reference implementation for extension authors (the file documents extension patterns; any new canonical example should be listed there)

**Out of tree (user-facing):**
When a user runs `vip scaffold --output ./my-custom-tests`, the tool writes the example files from `examples/cross_product_validation/` to `./my-custom-tests/`, ready to run with:
```bash
vip verify --config vip.toml --extensions ./my-custom-tests
```

## Verification

1. Selftest coverage:
   - `selftests/test_cli_scaffold.py` — new file; add a test that invokes `run_scaffold()` or the CLI entry with a temp output directory (note: `selftests/test_cli.py` does not exist; the existing CLI tests live in `selftests/test_cli_verify.py` which covers the `verify` subcommand)
   - **Assert on scaffolded content**, not just file existence:
     - `.feature` file carries `@connect @workbench` tags for auto-skip
     - `.py` step file imports from `pytest_bdd` (`from pytest_bdd import scenario, given, when, then`)
     - `conftest.py` defines the expected-version fixtures
   - Use `pytester` or `tmp_path` fixture to isolate the test

2. Manual verification (demo):
   ```bash
   # Confirm scaffold appears in CLI help so users can discover it
   uv run vip --help
   # Should list "scaffold" as a subcommand

   uv run vip scaffold --help
   # Should describe --output option and mention vip.toml.example for config reference

   uv run vip scaffold --output /tmp/cross-product-tests
   ls /tmp/cross-product-tests
   # Should contain: test_gxp_validation.feature, test_gxp_validation.py, conftest.py, README.md

   # Also verify that vip.toml.example covers the [runtimes] block users need to
   # configure r_versions / python_versions for the example tests
   grep -A5 '\[runtimes\]' vip.toml.example

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
  - **Decision:** Defer rename to a follow-up issue/PR to keep this PR focused on scaffolding.

## Out of scope

- Generating the `vip.toml` configuration file itself (users can already run `cp vip.toml.example vip.toml`).
- Integration with the Shiny app UI to invoke the scaffold command (the Shiny app is for running tests, not generating them).
- CI workflow changes (this is a documentation and CLI usability enhancement, not a test suite change).
- Renaming `examples/custom_tests/` → `examples/http_health_check/` (deferred to follow-up to keep this PR focused on scaffolding; see Open Questions).
- Duplicating the Workbench session-dialog version-check UI scenarios from PR #327 / #303 — the built-in suite covers those; the example focuses on the extension-author use case and package install verification.
