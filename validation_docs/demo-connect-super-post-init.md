# Fix: ConnectConfig.__post_init__ now calls super().__post_init__()

*2026-03-10T03:21:29Z by Showboat 0.6.1*
<!-- showboat-id: b6aa0e4d-9d98-4614-88f5-3c8e84c5b518 -->

ConnectConfig.__post_init__ was overriding ProductConfig.__post_init__ without calling super(), causing URL normalization (adding a default http:// scheme when no scheme is present) to be silently skipped for Connect configurations. Added super().__post_init__() call and a test to cover the regression.

```bash
uv run pytest selftests/test_config.py -v 2>&1 | tail -20
```

```output
selftests/test_config.py::TestConnectConfig::test_url_normalized_when_scheme_missing PASSED [ 29%]
selftests/test_config.py::TestConnectConfig::test_default_deploy_timeout PASSED [ 33%]
selftests/test_config.py::TestConnectConfig::test_explicit_deploy_timeout PASSED [ 37%]
selftests/test_config.py::TestVIPConfig::test_product_config_lookup PASSED [ 41%]
selftests/test_config.py::TestVIPConfig::test_product_config_unknown_raises PASSED [ 45%]
selftests/test_config.py::TestVIPConfig::test_defaults PASSED            [ 50%]
selftests/test_config.py::TestLoadConfig::test_missing_file_returns_defaults PASSED [ 54%]
selftests/test_config.py::TestLoadConfig::test_minimal_toml PASSED       [ 58%]
selftests/test_config.py::TestLoadConfig::test_disabled_product PASSED   [ 62%]
selftests/test_config.py::TestLoadConfig::test_extension_dirs PASSED     [ 66%]
selftests/test_config.py::TestLoadConfig::test_runtimes PASSED           [ 70%]
selftests/test_config.py::TestLoadConfig::test_data_sources PASSED       [ 75%]
selftests/test_config.py::TestLoadConfig::test_data_source_env_var PASSED [ 79%]
selftests/test_config.py::TestLoadConfig::test_env_var_config_path PASSED [ 83%]
selftests/test_config.py::TestLoadConfig::test_email_and_monitoring_flags PASSED [ 87%]
selftests/test_config.py::TestLoadConfig::test_deploy_timeout_from_toml PASSED [ 91%]
selftests/test_config.py::TestLoadConfig::test_deploy_timeout_defaults_when_missing PASSED [ 95%]
selftests/test_config.py::TestLoadConfig::test_full_config PASSED        [100%]

============================== 24 passed in 0.07s ==============================
```

```bash
uv run --with ruff ruff check src/ tests/ selftests/ examples/ 2>&1 | grep -v 'Downloading\|Downloaded\|Installed'; uv run --with ruff ruff format --check src/ tests/ selftests/ examples/ 2>&1 | grep -v 'Downloading\|Downloaded\|Installed'; echo 'All checks passed'
```

```output
All checks passed!
65 files already formatted
All checks passed
```
