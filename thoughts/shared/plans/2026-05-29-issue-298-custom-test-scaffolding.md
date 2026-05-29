# Plan for issue #298: add example of adding a custom test extension

## Context

Customers extending VIP for GxP deployments or other regulated environments need to verify specific R and Python versions are available and that critical bioinformatics packages (e.g., DESeq2, PyDeSEQ2) can install on both Workbench and Connect. While VIP already supports loading external test directories via `--extensions` or `extension_dirs` in `vip.toml`, the current `examples/custom_tests/` example is minimal — it demonstrates only a simple HTTP health check, not the cross-product runtime/package verification pattern that GxP users need.

The issue author requests a complete working example that verifies:
- Specific R and Python versions are available in both Workbench and Connect
- R and Python packages can be installed successfully on both products
- The example should use DESeq2 (R) and PyDeSEQ2 (Python) as representative bioinformatics packages

The preferred implementation is a `vip scaffold` or `vip init-extension` subcommand that generates a ready-to-run custom test directory with this pattern baked in. The alternative is documentation-only, but that requires users to copy-paste significant boilerplate.

## Architecture

This lands in two places:

1. **`src/vip/cli.py`** — add a new `scaffold` subcommand that writes the example test files to a user-specified directory
2. **`examples/cross_product_validation/`** — a reference implementation directory containing:
   - `.feature` file describing runtime and package verification scenarios
   - `.py` step definition file that uses existing VIP fixtures (`workbench_client`, `connect_client`, `expected_r_versions`, `expected_python_versions`)
   - `conftest.py` with fixtures for expected package lists (e.g., `@pytest.fixture def required_r_packages()`)
   - Optional: a sample `vip.toml` snippet showing how to configure `extension_dirs`

The `scaffold` command copies the reference directory to the user's target path and optionally templates in their specific version and package requirements.

## Components

**New files:**
- `examples/cross_product_validation/test_runtime_validation.feature` — Gherkin scenarios for version and package checks
- `examples/cross_product_validation/test_runtime_validation.py` — step definitions using VIP's client fixtures
- `examples/cross_product_validation/conftest.py` — fixtures for required packages, customizable by users
- `examples/cross_product_validation/README.md` — explains the example and how to customize it

**Modified files:**
- `src/vip/cli.py` — add `scaffold` subcommand and handler function `run_scaffold(args)`

**Out of tree (user-facing):**
When a user runs `vip scaffold --output ./my-custom-tests`, the tool writes the example files from `examples/cross_product_validation/` to `./my-custom-tests/`, ready to run with:
```bash
vip verify --config vip.toml --extensions ./my-custom-tests
```

## Verification

1. Selftest coverage:
   - `selftests/test_cli.py` — add a test that invokes `run_scaffold()` or the CLI entry with a temp output directory and verifies the expected files are created
   - Use `pytester` or `tmp_path` fixture to isolate the test

2. Manual verification (demo):
   ```bash
   uv run vip scaffold --output /tmp/cross-product-tests
   ls /tmp/cross-product-tests
   # Should contain: test_runtime_validation.feature, test_runtime_validation.py, conftest.py, README.md
   
   uv run vip verify --connect-url https://demo.connect --workbench-url https://demo.workbench \
     --extensions /tmp/cross-product-tests --collect-only
   # Should discover the new custom test scenarios
   ```

3. Linting:
   ```bash
   uv run ruff check src/ examples/ selftests/
   uv run ruff format --check src/ examples/ selftests/
   ```

## Open questions

- **UNCONFIRMED:** Should the `scaffold` command template in version/package requirements interactively (prompt the user), or simply copy the files and expect the user to edit `conftest.py` afterward?
  - **Leaning toward:** simple file copy + README instructions. Interactive templating adds complexity and most users will want to hand-edit their requirements anyway.

- **CONFIRMED:** Should the example test directory be named `examples/gxp_validation/` or something more generic like `examples/cross_product_validation/`?
  - **Decision:** `examples/cross_product_validation/` because the pattern applies beyond GxP (any customer who needs to lock runtime/package versions).

- **UNCONFIRMED:** Should the scaffold command default to copying from `examples/cross_product_validation/` or should it be extensible (multiple scaffold templates)?
  - **Leaning toward:** single template for now; extensibility can be added later if demand emerges.

## Out of scope

- Modifying the existing `examples/custom_tests/` directory (it serves a different purpose: minimal HTTP check). The new example is complementary, not a replacement.
- Generating the `vip.toml` configuration file itself (users can already run `cp vip.toml.example vip.toml`).
- Automation of package installation verification on the server side (the tests will attempt install via API and report success/failure; they won't modify server package caches or R library paths directly).
- Integration with the Shiny app UI to invoke the scaffold command (the Shiny app is for running tests, not generating them).
- CI workflow changes (this is a documentation and CLI usability enhancement, not a test suite change).
