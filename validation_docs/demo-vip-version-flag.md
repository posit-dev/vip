# Feature: vip --version and --product-versions (#463)

*2026-07-15T17:05:29Z by Showboat 0.6.1*
<!-- showboat-id: c541337b-6c4c-4a51-b383-31df29cab912 -->

Issue #463: `vip --version` errored with 'unrecognized arguments'. This wires up a standard `--version` action plus a `--product-versions` flag that prints the Posit product versions this release of vip targets (a curated constant in src/vip/version.py, keyed by display name).

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

```bash
uv run --project . pytest selftests/test_cli_version.py -q 2>&1 | grep -E 'passed|failed' | sed 's/ in [0-9.]*s//'
```

```output
5 passed
```

```bash
uv run --project . ruff check src/vip/cli.py src/vip/version.py selftests/test_cli_version.py
```

```output
All checks passed!
```
