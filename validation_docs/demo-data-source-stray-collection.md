# Fix: data-source step no longer collected as a stray test

*2026-05-31T20:31:53Z by Showboat 0.6.1*
<!-- showboat-id: b968a66d-6174-407a-b981-61678a8b2ae9 -->

## The bug

Running `vip verify --package-manager-url ...` errored with:

    ERROR at setup of test_connectivity
    test_connectivity: an unexpected error occurred: ValueError: connect_client did not yield a value

A Connect test was running during a Package-Manager-only verify.

## Root cause

The Connect `@when` step for "I test connectivity to each data source" was named
`test_connectivity`. Because it matched pytest's `python_functions = test_*`
collection pattern, pytest collected it as a standalone test in addition to
registering it as a pytest-bdd step.

That stray test carried none of the feature file's `@connect` marker (the marker
is applied only to the `@scenario` function), so the plugin's product deselection
in `_should_deselect_for_product` never excluded it. It ran during a
Package-Manager-only run, where the Connect dir's autouse cleanup fixtures pull in
the `connect_client` fixture — which `return`s (instead of `yield`s) when Connect
is unconfigured, raising `connect_client did not yield a value`.

## The fix

Rename the step to `check_connectivity_to_each_data_source` (the function name is
arbitrary — the step is matched by its Gherkin string), and add a selftest that
fails if any `@given`/`@when`/`@then` step function is named `test_*`.

```bash
grep -nE "def (test_connectivity|check_connectivity_to_each_data_source)" src/vip_tests/connect/test_data_sources.py
```

```output
23:def check_connectivity_to_each_data_source(data_sources, vip_config):
```

```bash
printf "[general]\ndeployment_name = \"X\"\n[package_manager]\nurl = \"https://example.com\"\n" > /tmp/vip_pm_demo.toml
echo "Collecting Connect data-source tests with a Package-Manager-only config:"
uv run pytest src/vip_tests/connect/test_data_sources.py --collect-only --vip-config=/tmp/vip_pm_demo.toml 2>&1 | grep "^collected"
```

```output
Collecting Connect data-source tests with a Package-Manager-only config:
collected 1 item / 1 deselected / 0 selected
```

```bash
uv run pytest selftests/test_step_naming.py -q 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
```

```output
1 passed
```

```bash
just check
```

```output
uv run ruff check src/ selftests/ examples/ docker/
All checks passed!
uv run ruff format --check src/ selftests/ examples/ docker/
136 files already formatted
```
