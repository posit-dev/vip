# Minimal example

The smallest possible VIP test extension: a single scenario that checks your
own configured Connect deployment. Start here, then copy the pattern to add
more scenarios.

Generate this directory from scratch using:

```bash
vip scaffold --template minimal --output ./my-custom-tests
```

## What this example tests

| Scenario | Product | Layer |
|---|---|---|
| Custom endpoint responds successfully | Connect API | httpx |

## Running the example

```bash
# Run with a vip.toml that has Connect configured
vip verify --config vip.toml --extensions .

# Dry-run: collect tests without executing
vip verify --config vip.toml --extensions . --collect-only
```

## Customizing

Edit `test_custom_check.py` and `test_custom_check.feature` to check your own
endpoint instead of Connect's `/server_settings`, or to add more scenarios.
Follow VIP's four-layer test architecture:

1. Add a `Scenario:` block to `test_custom_check.feature`
2. Add step definitions in `test_custom_check.py`
3. Add the `@pytest.mark.connect` (or `@pytest.mark.workbench` /
   `@pytest.mark.package_manager`) decorator on the `@scenario` function so
   auto-skip works correctly

## Further reading

- `AGENTS.md` -- fixture, marker, and client reference for writing extensions
- `docs/test-architecture.md` -- VIP's four-layer test architecture guide
- `examples/cross_product_validation/` -- a fuller example spanning Connect and Workbench
