# Feature: vip --version and --minimum-supported-version (#463)

*2026-07-15T17:43:22Z by Showboat 0.6.1*
<!-- showboat-id: a69cf791-7e2d-4296-8261-52935ee06228 -->

Issue #463: `vip --version` errored with 'unrecognized arguments'. This adds a standard `--version` action, plus `--minimum-supported-version` which prints the oldest Posit Team release this build of VIP officially supports. That floor is a deliberate support-policy decision (MINIMUM_SUPPORTED_POSIT_TEAM in src/vip/version.py) -- distinct from the per-test @min_version feature gates, which limit which tests run and are separate from what the stack supports.

```bash
uv run --project . vip --version
```

```output
vip 0.53.1
```

```bash
uv run --project . vip --minimum-supported-version
```

```output
Minimum supported Posit Team version: 2026.04.0
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
