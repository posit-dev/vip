# Feature: vip --version flag and vip version subcommand (#463)

*2026-07-15T17:53:16Z by Showboat 0.6.1*
<!-- showboat-id: f4320af4-2478-4887-8e52-dd3f061185c5 -->

Issue #463: `vip --version` errored with 'unrecognized arguments'. This adds the conventional `--version` flag (one-line), plus a `vip version` subcommand for the fuller view. Keeping --version/--help as the only flags and everything else as subcommands makes the CLI surface consistent. `vip version` also reports MINIMUM_SUPPORTED_POSIT_TEAM -- the oldest Posit Team release this build officially supports (a declared support-policy floor, distinct from the per-test @min_version feature gates).

```bash
uv run --project . vip --version
```

```output
vip 0.53.1
```

```bash
uv run --project . vip version
```

```output
vip 0.53.1
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
