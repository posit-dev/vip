"""Tests for vip.verify.credentials module.

These tests patch subprocess.run and the interactive auth helpers so that no
real kubectl or network calls are made.  They verify that credential key names
written to K8s Secrets match the env var names that config.py reads.
"""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decode_secret_data(data: dict[str, str]) -> dict[str, str]:
    """Decode base64-encoded Secret data values."""
    return {k: base64.b64decode(v).decode() for k, v in data.items()}


# ---------------------------------------------------------------------------
# Tests for _create_credentials_secret (Keycloak path)
# ---------------------------------------------------------------------------


class TestCreateCredentialsSecret:
    """_create_credentials_secret must write VIP_TEST_USERNAME / VIP_TEST_PASSWORD."""

    def test_secret_keys_match_env_var_names(self):
        from vip.verify.credentials import _create_credentials_secret

        captured_input = {}

        def fake_run(cmd, **kwargs):
            if "apply" in cmd:
                captured_input["json"] = kwargs.get("input", "")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("vip.verify.credentials.subprocess.run", side_effect=fake_run):
            _create_credentials_secret("alice", "s3cr3t", "posit-team")

        payload = json.loads(captured_input["json"])
        data = _decode_secret_data(payload["data"])

        assert "VIP_TEST_USERNAME" in data, "Secret must contain VIP_TEST_USERNAME key"
        assert "VIP_TEST_PASSWORD" in data, "Secret must contain VIP_TEST_PASSWORD key"

        # Old key names must NOT be present
        assert "username" not in data, "Old key 'username' must be removed"
        assert "password" not in data, "Old key 'password' must be removed"

    def test_secret_values_are_correct(self):
        from vip.verify.credentials import _create_credentials_secret

        captured_input = {}

        def fake_run(cmd, **kwargs):
            if "apply" in cmd:
                captured_input["json"] = kwargs.get("input", "")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("vip.verify.credentials.subprocess.run", side_effect=fake_run):
            _create_credentials_secret("bob", "mypassword", "posit-team")

        payload = json.loads(captured_input["json"])
        data = _decode_secret_data(payload["data"])

        assert data["VIP_TEST_USERNAME"] == "bob"
        assert data["VIP_TEST_PASSWORD"] == "mypassword"

    def test_secret_metadata(self):
        from vip.verify.credentials import _create_credentials_secret

        captured_input = {}

        def fake_run(cmd, **kwargs):
            if "apply" in cmd:
                captured_input["json"] = kwargs.get("input", "")
            return MagicMock(returncode=0, stdout="", stderr="")

        with patch("vip.verify.credentials.subprocess.run", side_effect=fake_run):
            _create_credentials_secret("carol", "pw", "my-namespace")

        payload = json.loads(captured_input["json"])
        assert payload["metadata"]["name"] == "vip-test-credentials"
        assert payload["metadata"]["namespace"] == "my-namespace"


# ---------------------------------------------------------------------------
# Tests for mint_interactive_credentials (interactive auth path)
# ---------------------------------------------------------------------------


class TestMintInteractiveCredentials:
    """mint_interactive_credentials must write VIP_CONNECT_API_KEY etc."""

    def _make_auth_session(self, api_key="ak-123", key_name="vip-key"):
        return SimpleNamespace(api_key=api_key, key_name=key_name)

    def test_credential_dict_key_names(self):
        from vip.verify.credentials import mint_interactive_credentials

        saved_credentials = {}

        def fake_save(namespace, credentials):
            saved_credentials.update(credentials)

        with (
            patch(
                "vip.verify.credentials.get_credentials_from_secret",
                return_value=None,
            ),
            patch(
                "vip.verify.credentials.start_interactive_auth",
                return_value=self._make_auth_session(),
            ),
            patch(
                "vip.verify.credentials.generate_workbench_token",
                return_value="wb-token-xyz",
            ),
            patch(
                "vip.verify.credentials.generate_pm_token",
                return_value="pm-token-abc",
            ),
            patch(
                "vip.verify.credentials.save_credentials_secret",
                side_effect=fake_save,
            ),
        ):
            mint_interactive_credentials("https://connect.example.com", "main", "posit-team")

        assert "VIP_CONNECT_API_KEY" in saved_credentials
        assert "VIP_CONNECT_KEY_NAME" in saved_credentials
        assert "VIP_WORKBENCH_API_KEY" in saved_credentials
        assert "VIP_PACKAGE_MANAGER_TOKEN" in saved_credentials

        # Old key names must NOT be present
        assert "connect-api-key" not in saved_credentials
        assert "connect-key-name" not in saved_credentials
        assert "workbench-token" not in saved_credentials
        assert "pm-token" not in saved_credentials

    def test_credential_dict_values(self):
        from vip.verify.credentials import mint_interactive_credentials

        saved_credentials = {}

        with (
            patch(
                "vip.verify.credentials.get_credentials_from_secret",
                return_value=None,
            ),
            patch(
                "vip.verify.credentials.start_interactive_auth",
                return_value=self._make_auth_session(api_key="my-api-key", key_name="my-key-name"),
            ),
            patch(
                "vip.verify.credentials.generate_workbench_token",
                return_value="wb-tok",
            ),
            patch(
                "vip.verify.credentials.generate_pm_token",
                return_value="pm-tok",
            ),
            patch(
                "vip.verify.credentials.save_credentials_secret",
                side_effect=lambda ns, creds: saved_credentials.update(creds),
            ),
        ):
            mint_interactive_credentials("https://connect.example.com", "main")

        assert saved_credentials["VIP_CONNECT_API_KEY"] == "my-api-key"
        assert saved_credentials["VIP_CONNECT_KEY_NAME"] == "my-key-name"
        assert saved_credentials["VIP_WORKBENCH_API_KEY"] == "wb-tok"
        assert saved_credentials["VIP_PACKAGE_MANAGER_TOKEN"] == "pm-tok"

    def test_skips_when_credentials_already_exist(self, capsys):
        from vip.verify.credentials import mint_interactive_credentials

        existing = {"VIP_CONNECT_API_KEY": "already-there"}

        with (
            patch(
                "vip.verify.credentials.get_credentials_from_secret",
                return_value=existing,
            ),
            patch("vip.verify.credentials.start_interactive_auth") as mock_auth,
        ):
            mint_interactive_credentials("https://connect.example.com", "main")

        mock_auth.assert_not_called()
        out = capsys.readouterr().out
        assert "already exist" in out

    def test_raises_when_auth_produces_no_api_key(self):
        from vip.verify.credentials import mint_interactive_credentials

        with (
            patch(
                "vip.verify.credentials.get_credentials_from_secret",
                return_value=None,
            ),
            patch(
                "vip.verify.credentials.start_interactive_auth",
                return_value=SimpleNamespace(api_key=None, key_name=None),
            ),
        ):
            with pytest.raises(RuntimeError, match="API key"):
                mint_interactive_credentials("https://connect.example.com", "main")


# ---------------------------------------------------------------------------
# Tests for cleanup_credentials
# ---------------------------------------------------------------------------


class TestCleanupCredentials:
    """cleanup_credentials must read VIP_CONNECT_API_KEY and VIP_CONNECT_KEY_NAME."""

    def test_reads_new_key_names_for_api_key_deletion(self):
        from vip.verify.credentials import cleanup_credentials

        existing = {
            "VIP_CONNECT_API_KEY": "ak-del",
            "VIP_CONNECT_KEY_NAME": "key-name-del",
        }

        deleted_key_name = {}

        def fake_delete_api_key(connect_url, api_key, key_name):
            deleted_key_name["api_key"] = api_key
            deleted_key_name["key_name"] = key_name

        def fake_run(cmd, **kwargs):
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch(
                "vip.verify.credentials.get_credentials_from_secret",
                return_value=existing,
            ),
            patch(
                "vip.verify.credentials._delete_api_key",
                side_effect=fake_delete_api_key,
            ),
            patch("vip.verify.credentials.subprocess.run", side_effect=fake_run),
        ):
            cleanup_credentials("posit-team", connect_url="https://connect.example.com")

        assert deleted_key_name["api_key"] == "ak-del"
        assert deleted_key_name["key_name"] == "key-name-del"

    def test_skips_api_key_deletion_when_connect_url_not_provided(self):
        from vip.verify.credentials import cleanup_credentials

        existing = {
            "VIP_CONNECT_API_KEY": "ak-del",
            "VIP_CONNECT_KEY_NAME": "key-name-del",
        }

        def fake_run(cmd, **kwargs):
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch(
                "vip.verify.credentials.get_credentials_from_secret",
                return_value=existing,
            ),
            patch("vip.verify.credentials._delete_api_key") as mock_delete,
            patch("vip.verify.credentials.subprocess.run", side_effect=fake_run),
        ):
            cleanup_credentials("posit-team")  # no connect_url

        mock_delete.assert_not_called()

    def test_skips_api_key_deletion_when_secret_has_no_credentials(self):
        from vip.verify.credentials import cleanup_credentials

        def fake_run(cmd, **kwargs):
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch(
                "vip.verify.credentials.get_credentials_from_secret",
                return_value=None,
            ),
            patch("vip.verify.credentials._delete_api_key") as mock_delete,
            patch("vip.verify.credentials.subprocess.run", side_effect=fake_run),
        ):
            cleanup_credentials("posit-team", connect_url="https://connect.example.com")

        mock_delete.assert_not_called()

    def test_does_not_read_old_key_names(self):
        """Verify cleanup_credentials does NOT look for old key names."""
        from vip.verify.credentials import cleanup_credentials

        # Provide only the OLD key names — cleanup should not use them
        old_style = {
            "connect-api-key": "old-ak",
            "connect-key-name": "old-key-name",
        }

        deleted_key_name = {}

        def fake_delete_api_key(connect_url, api_key, key_name):
            deleted_key_name["called"] = True

        def fake_run(cmd, **kwargs):
            return MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch(
                "vip.verify.credentials.get_credentials_from_secret",
                return_value=old_style,
            ),
            patch(
                "vip.verify.credentials._delete_api_key",
                side_effect=fake_delete_api_key,
            ),
            patch("vip.verify.credentials.subprocess.run", side_effect=fake_run),
        ):
            cleanup_credentials("posit-team", connect_url="https://connect.example.com")

        # Should NOT have called _delete_api_key because new key names are absent
        assert "called" not in deleted_key_name
