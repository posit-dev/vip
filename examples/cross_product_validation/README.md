# Cross-product validation example

This example demonstrates how to write a VIP test extension that verifies
runtime version requirements and package installability across both Workbench
and Connect. It is designed as a starting point for GxP deployments and other
regulated environments that need to verify specific software configurations.

Generate this directory from scratch using:

```bash
vip scaffold --output ./my-custom-tests
```

## What this example tests

| Scenario | Product | Layer |
|---|---|---|
| Connect R versions match requirements | Connect API | httpx |
| Connect Python versions match requirements | Connect API | httpx |
| R package (jsonlite) is installable on Connect | Connect API + bundle deploy | httpx |
| Python package (PyDeSEQ2) is installable on Connect | Connect API + bundle deploy | httpx |
| R package installable in Workbench RStudio session | Workbench terminal | Playwright |

## Running the example

```bash
# Run with a vip.toml that has both Connect and Workbench configured
vip verify --config vip.toml --extensions .

# Dry-run: collect tests without executing
vip verify --config vip.toml --extensions . --collect-only

# Skip the slow package-install scenarios
# Edit conftest.py and set check_packages to return False
```

## Configuration

Add a `[runtimes]` block to your `vip.toml` to specify the versions to check:

```toml
[runtimes]
r_versions = ["4.4.0", "4.3.1"]
python_versions = ["3.11.0", "3.10.0"]
```

Without a `[runtimes]` block, the version-check scenarios are skipped automatically.

## Customizing

### Change the packages being verified

Edit `conftest.py` and override the `r_package_name` and `python_package_name` fixtures:

```python
@pytest.fixture(scope="session")
def r_package_name() -> str:
    return "ggplot2"

@pytest.fixture(scope="session")
def python_package_name() -> str:
    return "pandas"
```

### Skip install checks

Set `check_packages` to `False` in `conftest.py` when you only need
runtime-version verification (much faster):

```python
@pytest.fixture(scope="session")
def check_packages() -> bool:
    return False
```

### Add more scenarios

Follow VIP's four-layer test architecture:

1. Add a `Scenario:` block to `test_gxp_validation.feature`
2. Add step definitions in `test_gxp_validation.py`
3. Add the `@pytest.mark.connect` or `@pytest.mark.workbench` decorator on the
   `@scenario` function so auto-skip works correctly

## Further reading

- `src/vip_tests/connect/test_packages.py` — full Connect package source verification
- `src/vip_tests/workbench/test_packages.py` — Workbench package install patterns
- `src/vip_tests/workbench/exec.py` — `terminal_run`, `rstudio_eval` primitives
- `docs/test-architecture.md` — VIP's four-layer test architecture guide
- `examples/custom_tests/` — simpler HTTP health-check extension example
