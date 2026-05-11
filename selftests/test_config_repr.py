"""Tests that sensitive fields are redacted in repr() output for config dataclasses.

Secret fields show '***' when populated and '' when empty — preserving the diagnostic
signal that a field was set without leaking its value into test output or CI logs.
"""

from __future__ import annotations

from vip.config import (
    AuthConfig,
    ConnectConfig,
    DataSourceEntry,
    PackageManagerConfig,
    VIPConfig,
    WorkbenchConfig,
)


class TestConnectConfigRepr:
    def test_api_key_is_redacted_when_set(self):
        cfg = ConnectConfig(url="https://connect.example.com", api_key="secret-key-abc123")
        r = repr(cfg)
        assert "secret-key-abc123" not in r
        assert "'***'" in r

    def test_api_key_is_empty_string_when_unset(self, monkeypatch):
        monkeypatch.delenv("VIP_CONNECT_API_KEY", raising=False)
        cfg = ConnectConfig(url="https://connect.example.com", api_key="")
        r = repr(cfg)
        assert "'***'" not in r
        assert "api_key=''" in r

    def test_non_secret_fields_appear_in_repr(self):
        cfg = ConnectConfig(url="https://connect.example.com", api_key="secret")
        r = repr(cfg)
        assert "https://connect.example.com" in r
        assert "ConnectConfig(" in r


class TestWorkbenchConfigRepr:
    def test_api_key_is_redacted_when_set(self):
        cfg = WorkbenchConfig(url="https://workbench.example.com", api_key="wb-secret-456")
        r = repr(cfg)
        assert "wb-secret-456" not in r
        assert "'***'" in r

    def test_api_key_is_empty_string_when_unset(self, monkeypatch):
        monkeypatch.delenv("VIP_WORKBENCH_API_KEY", raising=False)
        cfg = WorkbenchConfig(url="https://workbench.example.com", api_key="")
        r = repr(cfg)
        assert "'***'" not in r
        assert "api_key=''" in r

    def test_non_secret_fields_appear_in_repr(self):
        cfg = WorkbenchConfig(url="https://workbench.example.com", api_key="secret")
        r = repr(cfg)
        assert "https://workbench.example.com" in r
        assert "WorkbenchConfig(" in r


class TestPackageManagerConfigRepr:
    def test_token_is_redacted_when_set(self):
        cfg = PackageManagerConfig(url="https://pm.example.com", token="pm-token-789")
        r = repr(cfg)
        assert "pm-token-789" not in r
        assert "'***'" in r

    def test_token_is_empty_string_when_unset(self, monkeypatch):
        monkeypatch.delenv("VIP_PACKAGE_MANAGER_TOKEN", raising=False)
        monkeypatch.delenv("VIP_PM_TOKEN", raising=False)
        cfg = PackageManagerConfig(url="https://pm.example.com", token="")
        r = repr(cfg)
        assert "'***'" not in r
        assert "token=''" in r

    def test_non_secret_fields_appear_in_repr(self):
        cfg = PackageManagerConfig(url="https://pm.example.com", token="secret")
        r = repr(cfg)
        assert "https://pm.example.com" in r
        assert "PackageManagerConfig(" in r


class TestAuthConfigRepr:
    def test_password_is_redacted_when_set(self):
        cfg = AuthConfig(username="admin", password="hunter2")
        r = repr(cfg)
        assert "hunter2" not in r
        assert "'***'" in r

    def test_password_is_empty_string_when_unset(self, monkeypatch):
        monkeypatch.delenv("VIP_TEST_PASSWORD", raising=False)
        cfg = AuthConfig(username="admin", password="")
        r = repr(cfg)
        assert "'***'" not in r
        assert "password=''" in r

    def test_non_secret_fields_appear_in_repr(self):
        cfg = AuthConfig(username="admin", password="secret")
        r = repr(cfg)
        assert "admin" in r
        assert "AuthConfig(" in r


class TestDataSourceEntryRepr:
    def test_connection_string_is_redacted_when_set(self):
        entry = DataSourceEntry(
            name="mydb", type="postgres", connection_string="postgresql://user:pass@host/db"
        )
        r = repr(entry)
        assert "postgresql://user:pass@host/db" not in r
        assert "'***'" in r

    def test_connection_string_is_empty_string_when_unset(self):
        entry = DataSourceEntry(name="mydb", type="postgres", connection_string="")
        r = repr(entry)
        assert "'***'" not in r
        assert "connection_string=''" in r

    def test_non_secret_fields_appear_in_repr(self):
        entry = DataSourceEntry(name="mydb", type="postgres", connection_string="secret")
        r = repr(entry)
        assert "mydb" in r
        assert "DataSourceEntry(" in r


class TestVIPConfigReprDoesNotLeakSecrets:
    """Ensure repr(VIPConfig(...)) does not expose any plaintext secret.

    pytest's assertion rewriting recurses into nested objects by calling their
    __repr__, so this is the real-world scenario from the issue.
    """

    def test_vipconfig_repr_does_not_contain_secrets(self):
        cfg = VIPConfig(
            connect=ConnectConfig(url="https://connect.example.com", api_key="connect-secret"),
            workbench=WorkbenchConfig(url="https://workbench.example.com", api_key="wb-secret"),
            package_manager=PackageManagerConfig(url="https://pm.example.com", token="pm-secret"),
            auth=AuthConfig(username="admin", password="auth-secret"),
            data_sources=[
                DataSourceEntry(name="db", type="postgres", connection_string="conn-secret")
            ],
        )
        r = repr(cfg)
        assert "connect-secret" not in r
        assert "wb-secret" not in r
        assert "pm-secret" not in r
        assert "auth-secret" not in r
        assert "conn-secret" not in r
