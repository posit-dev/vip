# Feature: vip --version and --product-versions (#463)

*2026-07-15T17:32:27Z by Showboat 0.6.1*
<!-- showboat-id: f638f9c9-5318-47af-86d1-865d660041fe -->

Issue #463: `vip --version` errored with 'unrecognized arguments'. This wires up a standard `--version` action plus a `--product-versions` flag. The product versions are DERIVED from the suite's @pytest.mark.min_version markers (src/vip/product_targets.py), so the output can never drift from what the tests actually require.

```bash
uv run --project . vip --version
```

```output
vip 0.53.1
```

```bash
uv run --project . vip --product-versions
```

```output
Posit product versions targeted by vip 0.53.1:
  Connect  2026.06.0
```

The 'Connect 2026.06.0' line above is not hard-coded -- it is the highest min_version floor found in the suite. Here is the marker it was derived from:

```bash
grep -rn 'pytest.mark.min_version' src/vip_tests/
```

```output
src/vip_tests/connect/test_chronicle.py:9:@pytest.mark.min_version(product="connect", version="2026.06.0")
```

```bash
uv run --project . pytest selftests/test_cli_version.py -q 2>&1 | grep -E 'passed|failed' | sed 's/ in [0-9.]*s//'
```

```output
11 passed
```

```bash
uv run --project . ruff check src/vip/cli.py src/vip/version.py src/vip/product_targets.py selftests/test_cli_version.py
```

```output
All checks passed!
```
