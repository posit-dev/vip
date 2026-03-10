# Fix: ConnectConfig.__post_init__ now calls super().__post_init__()

*2026-03-10T02:20:07Z by Showboat 0.6.1*
<!-- showboat-id: d4908856-8d75-4fa8-a846-83ef62afd080 -->

ConnectConfig.__post_init__ was overriding ProductConfig.__post_init__ without calling super(), causing URL normalization (adding a default http:// scheme when no scheme is present) to be silently skipped for Connect configurations. Added super().__post_init__() call and a test to cover the regression.

```bash
uv run pytest selftests/test_config.py -v 2>&1 | tail -15
```

```output
selftests/test_config.py::TestVIPConfig::test_product_config_lookup PASSED [ 40%]
selftests/test_config.py::TestVIPConfig::test_product_config_unknown_raises PASSED [ 45%]
selftests/test_config.py::TestVIPConfig::test_defaults PASSED            [ 50%]
selftests/test_config.py::TestLoadConfig::test_missing_file_returns_defaults PASSED [ 55%]
selftests/test_config.py::TestLoadConfig::test_minimal_toml PASSED       [ 60%]
selftests/test_config.py::TestLoadConfig::test_disabled_product PASSED   [ 65%]
selftests/test_config.py::TestLoadConfig::test_extension_dirs PASSED     [ 70%]
selftests/test_config.py::TestLoadConfig::test_runtimes PASSED           [ 75%]
selftests/test_config.py::TestLoadConfig::test_data_sources PASSED       [ 80%]
selftests/test_config.py::TestLoadConfig::test_data_source_env_var PASSED [ 85%]
selftests/test_config.py::TestLoadConfig::test_env_var_config_path PASSED [ 90%]
selftests/test_config.py::TestLoadConfig::test_email_and_monitoring_flags PASSED [ 95%]
selftests/test_config.py::TestLoadConfig::test_full_config PASSED        [100%]

============================== 20 passed in 0.05s ==============================
```

```bash
uv run --with ruff ruff check src/ tests/ selftests/ examples/ && uv run --with ruff ruff format --check src/ tests/ selftests/ examples/ && echo 'All checks passed'
```

```output
All checks passed!
64 files already formatted
All checks passed
```
