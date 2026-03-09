"""Tests for vip.verify.credentials module."""

from __future__ import annotations

import base64
import json
import string
from unittest.mock import Mock, patch

import pytest

from vip.verify.credentials import (
    _generate_password,
    cleanup_credentials,
    generate_pm_token,
    generate_workbench_token,
    get_credentials_from_secret,
    save_credentials_secret,
)


def test_generate_password_length_and_charset():
    """Test that generated passwords have correct length and character diversity."""
    password = _generate_password(32)
    assert len(password) == 32

    # Verify all character classes are present
    lower = string.ascii_lowercase
    upper = string.ascii_uppercase
    digits = string.digits
    special = "!@#$%^&*()-_=+[]{}|;:,.<>?"

    assert any(c in lower for c in password), "Missing lowercase character"
    assert any(c in upper for c in password), "Missing uppercase character"
    assert any(c in digits for c in password), "Missing digit"
    assert any(c in special for c in password), "Missing special character"


def test_generate_password_min_length_validation():
    """Test that password generation fails for lengths below 4."""
    with pytest.raises(ValueError, match="at least 4"):
        _generate_password(3)


def test_generate_password_uniqueness():
    """Test that generated passwords are unique (not deterministic)."""
    passwords = [_generate_password(32) for _ in range(10)]
    assert len(set(passwords)) == 10, "Generated passwords should be unique"


@patch("vip.verify.credentials.subprocess.run")
def test_generate_workbench_token(mock_run):
    """Test workbench token generation via kubectl exec."""
    mock_run.return_value = Mock(stdout="test-workbench-token\n", returncode=0)

    token = generate_workbench_token("main", "vip-test-user", "posit-team")

    assert token == "test-workbench-token"
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args == [
        "kubectl",
        "exec",
        "deploy/workbench-main",
        "-n",
        "posit-team",
        "--",
        "rstudio-server",
        "generate-api-token",
        "user",
        "vip-test",
        "vip-test-user",
    ]


@patch("vip.verify.credentials.subprocess.run")
def test_generate_pm_token(mock_run):
    """Test Package Manager token generation via kubectl exec."""
    mock_run.return_value = Mock(stdout="test-pm-token\n", returncode=0)

    token = generate_pm_token("main", "posit-team")

    assert token == "test-pm-token"
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args == [
        "kubectl",
        "exec",
        "deploy/package-manager-main",
        "-n",
        "posit-team",
        "--",
        "rspm",
        "create",
        "token",
        "--scope=repos:read",
        "--quiet",
    ]


@patch("vip.verify.credentials.subprocess.run")
def test_save_credentials_secret(mock_run):
    """Test saving credentials to K8s Secret."""
    mock_run.return_value = Mock(returncode=0, stdout="secret/vip-test-credentials created\n")

    credentials = {
        "connect-api-key": "test-key",
        "workbench-token": "wb-token",
        "pm-token": "pm-token",
    }

    save_credentials_secret("posit-team", credentials)

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd == ["kubectl", "apply", "-f", "-", "-n", "posit-team"]

    # Verify JSON payload
    stdin_data = kwargs["input"]
    secret_spec = json.loads(stdin_data)

    assert secret_spec["kind"] == "Secret"
    assert secret_spec["metadata"]["name"] == "vip-test-credentials"
    assert secret_spec["metadata"]["namespace"] == "posit-team"
    assert secret_spec["type"] == "Opaque"

    # Verify base64-encoded data
    data = secret_spec["data"]
    assert base64.b64decode(data["connect-api-key"]).decode() == "test-key"
    assert base64.b64decode(data["workbench-token"]).decode() == "wb-token"
    assert base64.b64decode(data["pm-token"]).decode() == "pm-token"


@patch("vip.verify.credentials.subprocess.run")
def test_get_credentials_from_secret(mock_run):
    """Test reading credentials from K8s Secret."""
    secret_data = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "vip-test-credentials", "namespace": "posit-team"},
        "type": "Opaque",
        "data": {
            "connect-api-key": base64.b64encode(b"test-key").decode(),
            "workbench-token": base64.b64encode(b"wb-token").decode(),
        },
    }

    mock_run.return_value = Mock(stdout=json.dumps(secret_data), returncode=0)

    credentials = get_credentials_from_secret("posit-team")

    assert credentials is not None
    assert credentials["connect-api-key"] == "test-key"
    assert credentials["workbench-token"] == "wb-token"

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args == [
        "kubectl",
        "get",
        "secret",
        "vip-test-credentials",
        "-n",
        "posit-team",
        "-o",
        "json",
    ]


@patch("vip.verify.credentials.subprocess.run")
def test_get_credentials_from_secret_not_found(mock_run):
    """Test that get_credentials_from_secret returns None when Secret doesn't exist."""
    from subprocess import CalledProcessError

    mock_run.side_effect = CalledProcessError(
        1,
        ["kubectl"],
        stderr='Error from server (NotFound): secrets "vip-test-credentials" not found',
    )

    credentials = get_credentials_from_secret("posit-team")

    assert credentials is None


@patch("vip.verify.credentials.subprocess.run")
def test_get_credentials_from_secret_other_error(mock_run):
    """Test that get_credentials_from_secret raises on non-NotFound errors."""
    from subprocess import CalledProcessError

    mock_run.side_effect = CalledProcessError(
        1, ["kubectl"], stderr="Error from server: connection refused"
    )

    with pytest.raises(CalledProcessError):
        get_credentials_from_secret("posit-team")


@patch("vip.verify.credentials.get_credentials_from_secret")
@patch("vip.verify.credentials.subprocess.run")
def test_cleanup_deletes_secret(mock_run, mock_get_creds):
    """Test cleanup_credentials deletes the K8s Secret."""
    mock_get_creds.return_value = None  # No credentials to clean up
    mock_run.return_value = Mock(returncode=0)

    cleanup_credentials("posit-team")

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args == [
        "kubectl",
        "delete",
        "secret",
        "vip-test-credentials",
        "-n",
        "posit-team",
        "--ignore-not-found",
    ]


@patch("vip.verify.credentials._delete_api_key")
@patch("vip.verify.credentials.get_credentials_from_secret")
@patch("vip.verify.credentials.subprocess.run")
def test_cleanup_deletes_api_key(mock_run, mock_get_creds, mock_delete_key):
    """Test cleanup_credentials deletes Connect API key when connect_url provided."""
    mock_get_creds.return_value = {
        "connect-api-key": "test-key",
        "connect-key-name": "test-key-name",
    }
    mock_run.return_value = Mock(returncode=0)

    cleanup_credentials("posit-team", connect_url="https://connect.example.com")

    # Verify API key deletion was attempted
    mock_delete_key.assert_called_once_with(
        "https://connect.example.com", "test-key", "test-key-name"
    )

    # Verify Secret deletion
    mock_run.assert_called_once()


@patch("vip.verify.credentials._delete_api_key")
@patch("vip.verify.credentials.get_credentials_from_secret")
@patch("vip.verify.credentials.subprocess.run")
def test_cleanup_handles_api_key_deletion_failure(
    mock_run, mock_get_creds, mock_delete_key, capsys
):
    """Test cleanup_credentials continues even if API key deletion fails."""
    mock_get_creds.return_value = {
        "connect-api-key": "test-key",
        "connect-key-name": "test-key-name",
    }
    mock_delete_key.side_effect = Exception("API deletion failed")
    mock_run.return_value = Mock(returncode=0)

    cleanup_credentials("posit-team", connect_url="https://connect.example.com")

    # Verify warning was printed
    captured = capsys.readouterr()
    assert "Warning: Could not delete Connect API key" in captured.out

    # Verify Secret deletion still happened
    mock_run.assert_called_once()
