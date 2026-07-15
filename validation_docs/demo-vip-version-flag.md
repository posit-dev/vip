# Feature: vip --version and --product-versions (#463)

*2026-07-15T16:38:59Z by Showboat 0.6.1*
<!-- showboat-id: 0972df56-6062-451b-988f-1bb2e0c43efc -->

Issue #463: `vip --version` errored with 'unrecognized arguments'. This wires up a standard `--version` action plus a `--product-versions` flag that prints the Posit product versions this release of vip targets (a curated constant in src/vip/version.py).

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
  connect  2026.06.0
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
