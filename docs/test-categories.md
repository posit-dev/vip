# Test Categories

## Categories

| Category | Marker | Description |
|---|---|---|
| Prerequisites | `prerequisites` | Components installed, auth configured, admins onboarded |
| Package Manager | `package_manager` | CRAN/PyPI mirrors, repos, private packages |
| Connect | `connect` | Login, content deploy, data sources, packages, email, runtimes |
| Workbench | `workbench` | Login, IDE launch, sessions, packages, data sources, runtimes |
| Cross-product | `cross_product` | SSL, monitoring, system resources |
| Performance | `performance` | Load times, package install speed, concurrency, resource usage |
| Security | `security` | HTTPS enforcement, auth policy, secrets storage |

Run a specific category:

```bash
pytest -m connect
pytest -m "performance and connect"
```

## Version support

Tests can be pinned to product versions with the `min_version` marker:

```python
@pytest.mark.min_version(product="connect", version="2024.05.0")
def test_new_api_feature():
    ...
```

Tests that target a version newer than the deployment under test are
automatically skipped.

## Extensibility

Customers can add site-specific tests without modifying the VIP source tree.

1. Create a directory with `.feature` and `.py` files following the same
   conventions as the built-in tests.
2. Point VIP at it via configuration or the CLI:

```toml
# vip.toml
[general]
extension_dirs = ["/opt/vip-custom-tests"]
```

```bash
pytest --vip-extensions=/opt/vip-custom-tests
```

The custom tests directory is added to pytest's collection path at runtime.
See `examples/custom_tests/` for a working example.
