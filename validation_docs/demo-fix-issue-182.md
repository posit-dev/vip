# Fix: separate config hygiene tests from product verification (#182)

*2026-04-18T01:37:25Z by Showboat 0.6.1*
<!-- showboat-id: 2f3d999e-5a04-48f3-92f3-dafbd875fa47 -->

Issue #182 reported that `test_no_plaintext_secrets` and `test_api_key_from_env` are self-tests of VIP's own configuration hygiene, not tests of the Posit product deployment. Mixing them into `vip verify` output confuses users.

This change:
- Moves those tests to a new `config_hygiene` category under `src/vip_tests/config_hygiene/`.
- Registers the `config_hygiene` marker in the plugin and `pyproject.toml`.
- Excludes `config_hygiene` from the default `vip verify` marker expression (opt-in via `--categories config-hygiene`).
- Applies the same default exclusion in the K8s Job path.
- Adds a `headless_auth` session fixture alongside the existing `interactive_auth` fixture.
- Leaves `test_api_key_from_env` skipping for both interactive and headless auth (the existing `interactive_auth` fixture already covered both, but the skip message is now clearer).

## Before

Previously, `vip verify` against a Posit Team deployment surfaced two
config hygiene failures that flagged the user's `vip.toml` rather than
anything about the deployment:

> `test_no_plaintext_secrets`: Plaintext secrets found in config file:
> `['api_key']`. Use environment variables instead.
>
> `test_api_key_from_env`: `VIP_CONNECT_API_KEY` environment variable is
> not set. Secrets should be provided via environment variables, not the
> config file.

These tests lived under the `security` category (auto-run by default).

## After

The tests live under a new `config_hygiene` category that is excluded from
default `vip verify` runs. Users opt in with `--categories config-hygiene`
when they want to audit their VIP configuration.

## New layout

```bash
ls src/vip_tests/config_hygiene/ | grep -v __pycache__
```

```output
__init__.py
conftest.py
test_secrets.feature
test_secrets.py
```

```bash
grep -H "^@" src/vip_tests/config_hygiene/test_secrets.feature
```

```output
src/vip_tests/config_hygiene/test_secrets.feature:@config_hygiene
```

## Default `vip verify` excludes config_hygiene

Set up a minimal vip.toml for the demo:

```bash
uv run vip verify --config /tmp/vip-demo.toml --no-auth -- --collect-only -q 2>&1 | grep -v 'Note:' | sed 's/ in [0-9.]*s//' | tail -20
```

```output
<Dir vip>
  <Dir src>
    <Package vip_tests>
      <Package connect>
        <Module test_data_sources.py>
          <Function test_connectivity>
      <Package cross_product>
        <Module test_monitoring.py>
          <Function test_monitoring_configured>
        <Module test_resources.py>
          <Function test_product_health>
      <Package performance>
        <Module test_resource_usage.py>
          <Function test_response_time_under_load>
          <Function test_prometheus_metrics>
      <Package security>
        <Module test_auth_policy.py>
          <Function test_auth_provider>

================ 6/100 tests collected (94 deselected) ================
```

Note that no `config_hygiene` tests were collected.

## Opt in with `--categories config-hygiene`

```bash
uv run vip verify --config /tmp/vip-demo.toml --no-auth --categories config-hygiene -- --collect-only -q 2>&1 | grep -v 'Note:' | sed 's/ in [0-9.]*s//' | tail -20
```

```output
============================= test session starts ==============================
collected 100 items / 99 deselected / 1 skipped / 1 selected

<Dir vip>
  <Dir src>
    <Package vip_tests>
      <Package config_hygiene>
        <Module test_secrets.py>
          <Function test_no_plaintext_secrets>

================ 1/100 tests collected (99 deselected) ================
```

## Selftests pass

243 existing tests plus 6 new tests covering the new behavior (default exclusion, explicit opt-in, normalizer accepting `config-hygiene`, `_default_marker_expr`, `headless_auth` fixture):

```bash
uv run pytest selftests/ -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
249 passed, 5 warnings
```

## Lint and format checks

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
101 files already formatted
```
