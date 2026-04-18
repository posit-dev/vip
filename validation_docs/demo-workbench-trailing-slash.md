# fix(config): normalize product URLs to include trailing slash

*2026-04-18T00:30:53Z by Showboat 0.6.1*
<!-- showboat-id: b0ee60d2-f349-4503-ad8c-ecb6143181c6 -->

Updated _normalize_url() in src/vip/config.py to ensure all product URLs end with a trailing slash. Without the slash, nginx redirects e.g. https://host/pwb to http://host/pwb/ (note: HTTP not HTTPS), which Playwright cannot follow in a headless HTTPS context. Since BaseClient already strips trailing slashes (rstrip('/')), API calls are unaffected. Added tests for the new behaviour and updated existing URL equality assertions to expect the trailing slash.

```bash
uv run pytest selftests/test_config.py -v 2>&1 | tail -25
```

```output
selftests/test_config.py::TestLoadConfig::test_extension_dirs PASSED     [ 63%]
selftests/test_config.py::TestLoadConfig::test_runtimes PASSED           [ 65%]
selftests/test_config.py::TestLoadConfig::test_data_sources PASSED       [ 68%]
selftests/test_config.py::TestLoadConfig::test_data_source_env_var PASSED [ 70%]
selftests/test_config.py::TestLoadConfig::test_env_var_config_path PASSED [ 72%]
selftests/test_config.py::TestLoadConfig::test_email_and_monitoring_flags PASSED [ 75%]
selftests/test_config.py::TestLoadConfig::test_performance_section PASSED [ 77%]
selftests/test_config.py::TestLoadConfig::test_performance_defaults_when_section_missing PASSED [ 79%]
selftests/test_config.py::TestLoadConfig::test_deploy_timeout_from_toml PASSED [ 81%]
selftests/test_config.py::TestLoadConfig::test_deploy_timeout_defaults_when_missing PASSED [ 84%]
selftests/test_config.py::TestLoadConfig::test_full_config PASSED        [ 86%]
selftests/test_config.py::TestMode::test_enum_values PASSED              [ 88%]
selftests/test_config.py::TestMode::test_str_comparison PASSED           [ 90%]
selftests/test_config.py::TestVIPConfigValidateForMode::test_local_mode_no_cluster_required PASSED [ 93%]
selftests/test_config.py::TestVIPConfigValidateForMode::test_k8s_job_requires_cluster PASSED [ 95%]
selftests/test_config.py::TestVIPConfigValidateForMode::test_k8s_job_passes_with_cluster PASSED [ 97%]
selftests/test_config.py::TestVIPConfigValidateForMode::test_config_only_requires_cluster PASSED [100%]

=============================== warnings summary ===============================
selftests/test_config.py::TestLoadConfig::test_missing_file_returns_defaults
  /home/runner/work/vip/vip/selftests/test_config.py:164: UserWarning: Config file not found: /tmp/pytest-of-runner/pytest-2/test_missing_file_returns_defa0/nonexistent.toml
    cfg = load_config(tmp_path / "nonexistent.toml")

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 44 passed, 1 warning in 0.07s =========================
```

```bash
uv run pytest selftests/ 2>&1 | tail -5
```

```output
  /home/runner/work/vip/vip/src/vip/plugin.py:150: UserWarning: Config file not found: vip.toml
    vip_cfg = load_config(config.getoption("--vip-config"))

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 246 passed, 4 warnings in 11.99s =======================
```

```bash
uv tool run ruff check src/ selftests/ examples/ && uv tool run ruff format --check src/ selftests/ examples/ && echo 'All checks passed'
```

```output
All checks passed!
99 files already formatted
All checks passed
```
