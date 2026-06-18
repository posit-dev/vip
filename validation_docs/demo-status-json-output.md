# feat(cli): add --json output to vip status (#384)

*2026-06-17T21:21:33Z by Showboat 0.6.1*
<!-- showboat-id: 6674d762-7c49-4d7c-806f-a38e9756bf6e -->

Issue #384 asks for machine-readable output from `vip status` so headless/CI callers can consume the per-product health check without scraping stdout — the same programmatic parity `vip verify --report` already offers via results.json.

This adds a `--json` flag to `vip status`. The check loop was refactored into a pure `_collect_status(config)` helper so the text and JSON renderers, plus the 0/1 exit code, all derive from one source of truth. The JSON schema is aligned with reporting.py field names (`products` keyed by name, `configured`, `url`, `outcome`, `exit_status`).

### Default text mode is unchanged

```bash
uv run vip status 2>/dev/null
```

```output
  SKIP  connect               not configured
  SKIP  workbench             not configured
  SKIP  package_manager       not configured
```

### New machine-readable JSON mode

Diagnostics go to stderr, so stdout is pure JSON — pipe it straight into a parser:

```bash
uv run vip status --json 2>/dev/null | python -m json.tool
```

```output
{
    "products": {
        "connect": {
            "configured": false,
            "state": "skip",
            "detail": "not configured"
        },
        "workbench": {
            "configured": false,
            "state": "skip",
            "detail": "not configured"
        },
        "package_manager": {
            "configured": false,
            "state": "skip",
            "detail": "not configured"
        }
    },
    "outcome": "ok",
    "exit_status": 0
}
```

### New selftests (27, TDD'd — none existed for run_status before)

```bash
uv run pytest selftests/test_cli_status.py -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
27 passed
```

### Lint and format clean

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

```bash
uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
155 files already formatted
```
