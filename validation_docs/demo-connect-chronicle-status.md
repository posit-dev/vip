# test(connect): add chronicle status verification

*2026-06-16T20:25:46Z by Showboat 0.6.1*
<!-- showboat-id: e41df1cd-840a-45d7-a019-d38da14fc72b -->

Adds a VIP verification test for Connect's embedded Chronicle usage-data subprocess, using the new admin-only `GET /__api__/v1/system/chronicle` endpoint (posit-dev/connect#40652, merged 2026-06-16), which reports `{enabled, ready}`.

Following VIP's model (verify an operator's declared expectation against a live deployment), the test is scoped behind a `[chronicle] enabled` config flag and auto-skips when not declared — mirroring the existing email/monitoring features. No `min_version` gate and no CI provisioning, consistent with how other optional features are handled.

Changes:
- `src/vip/clients/connect.py` — `chronicle_status()` client method
- `src/vip_tests/connect/test_chronicle.feature` / `test_chronicle.py` — feature + steps
- `vip.toml.example` — documented `[chronicle] enabled` section
- `selftests/test_config.py` — config-loading assertions

Verified live against a local Chronicle-enabled Connect (2026.06+): the scenario passed with enabled=true and ready=true. That run is not included below because it requires a Chronicle-enabled server, which CI does not provide; the blocks below run anywhere.

## Config selftests pass (new chronicle flag loads, and defaults to disabled)

```bash
uv run pytest selftests/test_config.py -q 2>&1 | grep -E "passed|failed" | sed "s/ in [0-9.]*s//"
```

```output
100 passed, 1 warning
```

## The new BDD scenario collects

```bash
uv run pytest src/vip_tests/connect/test_chronicle.py --collect-only -q --vip-config vip.toml.example 2>&1 | grep -E "chronicle|collected" | sed "s/ in [0-9.]*s//"
```

```output
src/vip_tests/connect/test_chronicle.py::test_chronicle_status
1 test collected
```

## Lint and format are clean (ruff pinned to CI version 0.15.0)

```bash
uvx ruff@0.15.0 check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

```bash
uvx ruff@0.15.0 format --check src/ src/vip_tests/ selftests/ examples/ 2>&1 | tail -1
```

```output
155 files already formatted
```
