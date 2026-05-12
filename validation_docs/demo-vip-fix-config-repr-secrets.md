# Fix: redact secrets in config dataclass repr

*2026-05-11T16:34:02Z by Showboat 0.6.1*
<!-- showboat-id: 3b7b91f5-89e4-40b5-aee4-d1bc4c7eb73d -->

Config dataclasses (ConnectConfig, WorkbenchConfig, PackageManagerConfig, AuthConfig, DataSourceEntry) previously leaked secrets in their default repr, exposing API keys and passwords in CI logs and pytest assertion output. Issue #223: each class now has a custom __repr__ that prints sensitive fields as '***' when set and '' when empty. A new selftest file selftests/test_config_repr.py covers the change.

```bash
uv run python -c "
from vip.config import ConnectConfig, AuthConfig
c = ConnectConfig(url='https://connect.example.com', api_key='SECRET-12345')
a = AuthConfig(username='admin', password='hunter2')
print(repr(c))
print(repr(a))
"
```

```output
ConnectConfig(enabled=True, url='https://connect.example.com', version=None, api_key='***', deploy_timeout=1200)
AuthConfig(provider='password', username='admin', password='***', idp='')
```

```bash
uv run pytest selftests/test_config_repr.py -v 2>&1 | grep -E 'PASSED|FAILED' | sed 's/ \[.*\]//' | sort
```

```output
selftests/test_config_repr.py::TestAuthConfigRepr::test_non_secret_fields_appear_in_repr PASSED
selftests/test_config_repr.py::TestAuthConfigRepr::test_password_is_empty_string_when_unset PASSED
selftests/test_config_repr.py::TestAuthConfigRepr::test_password_is_redacted_when_set PASSED
selftests/test_config_repr.py::TestConnectConfigRepr::test_api_key_is_empty_string_when_unset PASSED
selftests/test_config_repr.py::TestConnectConfigRepr::test_api_key_is_redacted_when_set PASSED
selftests/test_config_repr.py::TestConnectConfigRepr::test_non_secret_fields_appear_in_repr PASSED
selftests/test_config_repr.py::TestDataSourceEntryRepr::test_connection_string_is_empty_string_when_unset PASSED
selftests/test_config_repr.py::TestDataSourceEntryRepr::test_connection_string_is_redacted_when_set PASSED
selftests/test_config_repr.py::TestDataSourceEntryRepr::test_non_secret_fields_appear_in_repr PASSED
selftests/test_config_repr.py::TestPackageManagerConfigRepr::test_non_secret_fields_appear_in_repr PASSED
selftests/test_config_repr.py::TestPackageManagerConfigRepr::test_token_is_empty_string_when_unset PASSED
selftests/test_config_repr.py::TestPackageManagerConfigRepr::test_token_is_redacted_when_set PASSED
selftests/test_config_repr.py::TestVIPConfigReprDoesNotLeakSecrets::test_vipconfig_repr_does_not_contain_secrets PASSED
selftests/test_config_repr.py::TestWorkbenchConfigRepr::test_api_key_is_empty_string_when_unset PASSED
selftests/test_config_repr.py::TestWorkbenchConfigRepr::test_api_key_is_redacted_when_set PASSED
selftests/test_config_repr.py::TestWorkbenchConfigRepr::test_non_secret_fields_appear_in_repr PASSED
```

```bash
uv run ruff check src/vip/config.py selftests/test_config_repr.py && uv run ruff format --check src/vip/config.py selftests/test_config_repr.py
```

```output
All checks passed!
2 files already formatted
```

The selftest suite covers 16 tests across all 5 config classes (ConnectConfig, WorkbenchConfig, PackageManagerConfig, AuthConfig, DataSourceEntry), with 3 tests per class validating redaction when set, empty-string display when unset, and non-secret field visibility. A 16th integration test (TestVIPConfigReprDoesNotLeakSecrets) constructs a full VIPConfig and asserts none of the 5 secret values appear in repr output.
