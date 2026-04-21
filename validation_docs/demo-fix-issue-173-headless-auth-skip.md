# fix(auth): skip headless auth when no auth-requiring products are enabled

*2026-04-18T01:31:19Z by Showboat 0.6.1*
<!-- showboat-id: 5e22069d-ab1a-415e-998b-ae78e99ef887 -->

Issue #173: When `vip verify --headless-auth` is invoked but neither Connect nor Workbench is configured (for instance, when only Package Manager is enabled), the plugin used to raise a `UsageError` and abort the run. Package Manager tests don't require browser authentication, so they should be able to run without any auth flow at all.

## Fix

In `src/vip/plugin.py`, the `--interactive-auth` and `--headless-auth` branches of `pytest_configure` now warn and skip the browser flow instead of raising `UsageError` when no auth-requiring product (Connect or Workbench) is configured. Tests continue to run -- Package Manager tests that don't need auth still proceed normally.

## Reproducing the reported scenario

We create an isolated fixture with Connect and Workbench disabled and Package Manager enabled, then invoke pytest with `--headless-auth`.  Before the fix this would abort with a `UsageError`.  After the fix, the plugin warns, skips the browser flow, and the placeholder test runs to completion.

```bash
rm -rf /tmp/vip-demo-173 && mkdir -p /tmp/vip-demo-173 && cat > /tmp/vip-demo-173/vip.toml <<'EOF'
[general]
deployment_name = "Issue 173 Repro"

[connect]
enabled = false

[workbench]
enabled = false

[package_manager]
enabled = true
url = "https://pm.example.com"
EOF
cat > /tmp/vip-demo-173/test_placeholder.py <<'EOF'
def test_pm_only_run():
    assert True
EOF
cat /tmp/vip-demo-173/vip.toml
```

```output
[general]
deployment_name = "Issue 173 Repro"

[connect]
enabled = false

[workbench]
enabled = false

[package_manager]
enabled = true
url = "https://pm.example.com"
```

```bash
VIP_ROOT=$PWD && cd /tmp/vip-demo-173 && uv --project "$VIP_ROOT" run pytest --vip-config=vip.toml --headless-auth test_placeholder.py 2>&1 | grep -E 'passed|failed|error|auth-requiring' | sed -E 's/ in [0-9.]+s//; s|.+/src/vip/plugin.py:[0-9]+:|src/vip/plugin.py:|'
```

```output
src/vip/plugin.py: UserWarning: VIP: --headless-auth was requested but no auth-requiring products (Connect, Workbench) are configured; skipping browser authentication.
============================== 1 passed ===============================
```

The placeholder test passes and the plugin emits a user-visible warning instead of aborting.  Package Manager-only workflows now succeed with `--headless-auth`.

## Selftest coverage

Three selftests cover the new behavior:

- `TestPluginIntegration::test_interactive_auth_skipped_when_no_auth_products` -- verifies `--interactive-auth` also skips gracefully.
- `TestHeadlessAuthFixture::test_headless_auth_skipped_when_no_auth_products` -- exercises `--headless-auth` with no products configured at all.
- `TestHeadlessAuthFixture::test_headless_auth_skipped_when_only_package_manager_enabled` -- reproduces the exact issue #173 scenario.

```bash
uv run pytest selftests/test_plugin.py -v -k 'auth_skipped or auth_skipped_when_only' 2>&1 | grep -E 'PASSED|FAILED|ERROR' | sed 's/ in [0-9.]*s//'
```

```output
selftests/test_plugin.py::TestPluginIntegration::test_interactive_auth_skipped_when_no_auth_products PASSED [ 33%]
selftests/test_plugin.py::TestHeadlessAuthFixture::test_headless_auth_skipped_when_no_auth_products PASSED [ 66%]
selftests/test_plugin.py::TestHeadlessAuthFixture::test_headless_auth_skipped_when_only_package_manager_enabled PASSED [100%]
```

## Full selftest suite

The rest of the selftest suite still passes and the existing `--headless-auth requires idp` validation remains in effect.

```bash
uv run pytest selftests/ 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
======================= 244 passed, 4 warnings =======================
```

## Lint and format

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ && uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
99 files already formatted
```
