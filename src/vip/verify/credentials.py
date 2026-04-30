"""Credential provisioning for VIP verification.

This module provides functions to create test users in Keycloak and mint
credentials for all Posit Team products (Connect, Workbench, Package Manager)
via a combination of interactive browser auth and kubectl exec commands.

Credentials are stored in a Kubernetes Secret named vip-test-credentials.
"""

from __future__ import annotations

import base64
import json
import secrets
import string
import subprocess
from pathlib import Path

import httpx

from vip.auth import _delete_api_key, start_interactive_auth

# Name of the K8s Secret that holds VIP test user credentials.
_VIP_TEST_CREDENTIALS_SECRET = "vip-test-credentials"


def ensure_keycloak_test_user(
    keycloak_url: str,
    realm: str,
    username: str,
    admin_secret_name: str,
    namespace: str = "posit-team",
    insecure: bool = False,
    ca_bundle: Path | None = None,
) -> None:
    """Create or reset a test user in Keycloak and store credentials in a K8s Secret.

    This function performs the following steps:
    1. Check if vip-test-credentials Secret exists (skip if present)
    2. Fetch Keycloak admin credentials from K8s Secret
    3. Get admin token from Keycloak master realm
    4. Create or reset test user
    5. Store credentials in K8s Secret

    Args:
        keycloak_url: Base URL of the Keycloak server (e.g., https://keycloak.example.com)
        realm: Keycloak realm name
        username: Username for the test user
        admin_secret_name: Name of the K8s Secret containing Keycloak admin credentials
        namespace: Kubernetes namespace (default: posit-team)

    Raises:
        subprocess.CalledProcessError: If kubectl commands fail
        httpx.HTTPError: If Keycloak API requests fail
        ValueError: If credentials are missing or invalid
    """
    # Check if the vip-test-credentials secret already exists
    check_cmd = [
        "kubectl",
        "get",
        "secret",
        _VIP_TEST_CREDENTIALS_SECRET,
        "-n",
        namespace,
        "--ignore-not-found",
        "-o",
        "json",
    ]
    result = subprocess.run(check_cmd, capture_output=True, text=True, check=True)

    if result.stdout.strip():
        secret_data = json.loads(result.stdout).get("data", {})
        if "username" in secret_data or "password" in secret_data:
            print(
                "Warning: Test credentials secret uses old key names ('username'/'password'). "
                "Run 'vip verify cleanup' to regenerate it with the current key names "
                "('VIP_TEST_USERNAME'/'VIP_TEST_PASSWORD')."
            )
        else:
            print("Test user credentials secret already exists, skipping creation")
        return

    print("Creating test user in Keycloak")

    # Get admin credentials from K8s Secret
    admin_username, admin_password = _get_secret_credentials(admin_secret_name, namespace)

    # Get admin access token
    token = _get_keycloak_admin_token(
        keycloak_url, admin_username, admin_password, insecure=insecure, ca_bundle=ca_bundle
    )

    # Generate a cryptographic random password
    password = _generate_password(32)

    # Create or reset the test user
    _create_keycloak_user(
        keycloak_url, realm, token, username, password, insecure=insecure, ca_bundle=ca_bundle
    )

    # Create the vip-test-credentials secret
    _create_credentials_secret(username, password, namespace)

    print(f"Test user created successfully: {username}")


def mint_interactive_credentials(
    connect_url: str,
    site_name: str,
    namespace: str = "posit-team",
    username: str = "vip-test-user",
) -> None:
    """Mint credentials for all products via interactive auth + kubectl exec.

    This function:
    1. Mints a Connect API key via VIP interactive auth (browser-based OIDC)
    2. Generates a Workbench token via kubectl exec
    3. Generates a Package Manager token via kubectl exec
    4. Saves all credentials to a K8s Secret

    Args:
        connect_url: Connect server URL
        site_name: Site name suffix for deployments (e.g., "main")
        namespace: Kubernetes namespace (default: posit-team)
        username: Username for the test user (default: vip-test-user)

    Raises:
        subprocess.CalledProcessError: If kubectl exec commands fail
        RuntimeError: If interactive auth fails
    """
    existing = get_credentials_from_secret(namespace)
    if existing and existing.get("VIP_CONNECT_API_KEY"):
        print("Credentials already exist in K8s Secret.")
        print("Run 'vip verify cleanup' first to re-mint credentials.")
        return

    print("Minting Connect API key via interactive auth...")
    auth_session = start_interactive_auth(connect_url)

    if not auth_session.api_key:
        raise RuntimeError("Interactive auth did not produce an API key")

    print(f"Connect API key created: {auth_session.key_name}")

    print("Generating Workbench token via kubectl exec...")
    workbench_token = generate_workbench_token(site_name, username, namespace)

    print("Generating Package Manager token via kubectl exec...")
    pm_token = generate_pm_token(site_name, username, namespace)

    credentials = {
        "VIP_CONNECT_API_KEY": auth_session.api_key,
        "VIP_CONNECT_KEY_NAME": auth_session.key_name,
        "VIP_WORKBENCH_API_KEY": workbench_token,
        "VIP_PACKAGE_MANAGER_TOKEN": pm_token,
    }

    print("Saving credentials to K8s Secret...")
    save_credentials_secret(namespace, credentials)

    print("All credentials minted and saved successfully")
    print("Run 'vip verify cleanup' to delete credentials when done")


def generate_workbench_token(
    site_name: str,
    username: str,
    namespace: str = "posit-team",
) -> str:
    """Generate a Workbench API token via kubectl exec.

    Args:
        site_name: Site name suffix for the deployment
        username: Username for token generation
        namespace: Kubernetes namespace

    Returns:
        The generated Workbench API token

    Raises:
        subprocess.CalledProcessError: If kubectl exec fails
    """
    deployment_name = f"workbench-{site_name}"
    cmd = [
        "kubectl",
        "exec",
        f"deploy/{deployment_name}",
        "-n",
        namespace,
        "--",
        "rstudio-server",
        "generate-api-token",
        "user",
        "vip-test",
        username,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def generate_pm_token(
    site_name: str,
    username: str,
    namespace: str = "posit-team",
) -> str:
    """Generate a Package Manager token via kubectl exec.

    Args:
        site_name: Site name suffix for the deployment
        username: Audit label for the token (stored in JWT sub claim)
        namespace: Kubernetes namespace

    Returns:
        The generated Package Manager API token

    Raises:
        subprocess.CalledProcessError: If kubectl exec fails
    """
    deployment_name = f"package-manager-{site_name}"
    cmd = [
        "kubectl",
        "exec",
        f"deploy/{deployment_name}",
        "-n",
        namespace,
        "--",
        "rspm",
        "create",
        "token",
        f"--user={username}",
        "--scope=repos:read",
        "--quiet",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _build_secret_spec(
    name: str,
    namespace: str,
    data_dict: dict[str, str],
    labels_dict: dict[str, str],
) -> dict:
    """Build a Kubernetes Secret spec dict.

    Args:
        name: Secret name
        namespace: Kubernetes namespace
        data_dict: Already-encoded (base64) key-value pairs for the Secret data field
        labels_dict: Labels to attach to the Secret metadata

    Returns:
        A dict representing the Secret spec, suitable for JSON serialisation
    """
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": labels_dict,
        },
        "type": "Opaque",
        "data": data_dict,
    }


def save_credentials_secret(
    namespace: str,
    credentials: dict[str, str],
) -> None:
    """Create or update the vip-test-credentials K8s Secret.

    Uses kubectl create --dry-run=client | kubectl apply for idempotency.

    Args:
        namespace: Kubernetes namespace
        credentials: Dictionary of credential key-value pairs

    Raises:
        subprocess.CalledProcessError: If kubectl commands fail
    """
    # Base64-encode all credential values for the Secret data field
    encoded_data = {
        key: base64.b64encode(value.encode()).decode() for key, value in credentials.items()
    }

    secret_spec = _build_secret_spec(
        name=_VIP_TEST_CREDENTIALS_SECRET,
        namespace=namespace,
        data_dict=encoded_data,
        labels_dict={
            "app.kubernetes.io/managed-by": "vip",
            "app.kubernetes.io/name": "vip-verify",
        },
    )

    secret_json = json.dumps(secret_spec)

    cmd = ["kubectl", "apply", "-f", "-", "-n", namespace]
    subprocess.run(
        cmd,
        input=secret_json,
        capture_output=True,
        text=True,
        check=True,
    )


def get_credentials_from_secret(
    namespace: str = "posit-team",
) -> dict[str, str] | None:
    """Read credentials from the vip-test-credentials K8s Secret.

    Args:
        namespace: Kubernetes namespace

    Returns:
        Dictionary of credential key-value pairs, or None if the Secret doesn't exist

    Raises:
        subprocess.CalledProcessError: If kubectl command fails (other than not found)
        ValueError: If Secret data is malformed
    """
    cmd = [
        "kubectl",
        "get",
        "secret",
        _VIP_TEST_CREDENTIALS_SECRET,
        "-n",
        namespace,
        "-o",
        "json",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        if "NotFound" in e.stderr or "not found" in e.stderr.lower():
            return None
        raise

    secret = json.loads(result.stdout)
    data = secret.get("data", {})

    # Decode base64-encoded values
    credentials = {}
    for key, value in data.items():
        credentials[key] = base64.b64decode(value).decode()

    return credentials


def cleanup_credentials(
    namespace: str,
    connect_url: str | None = None,
) -> None:
    """Delete VIP test credentials and resources.

    This function:
    1. Reads the Secret to get the Connect API key and key name
    2. Deletes the Connect API key via REST API (if connect_url provided)
    3. Deletes the K8s Secret

    Args:
        namespace: Kubernetes namespace
        connect_url: Connect server URL (optional, required to delete API key)

    Raises:
        subprocess.CalledProcessError: If kubectl commands fail
    """
    # Get credentials from the Secret first
    credentials = get_credentials_from_secret(namespace)

    if credentials and connect_url:
        api_key = credentials.get("VIP_CONNECT_API_KEY")
        key_name = credentials.get("VIP_CONNECT_KEY_NAME")

        if api_key and key_name:
            try:
                _delete_api_key(connect_url, api_key, key_name)
                print(f"Deleted Connect API key: {key_name}")
            except Exception as e:
                print(f"Warning: Could not delete Connect API key: {e}")

    # Delete the K8s Secret
    cmd = [
        "kubectl",
        "delete",
        "secret",
        _VIP_TEST_CREDENTIALS_SECRET,
        "-n",
        namespace,
        "--ignore-not-found",
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    print(f"Deleted Secret: {_VIP_TEST_CREDENTIALS_SECRET}")


# Private helper functions


def _generate_password(length: int = 32) -> str:
    """Generate a cryptographically random password.

    Guarantees at least one character from each class (lower, upper, digit, special)
    to satisfy password policies that require character diversity.

    Args:
        length: Password length (minimum 4)

    Returns:
        A random password string

    Raises:
        ValueError: If length is less than 4
    """
    if length < 4:
        raise ValueError("Password length must be at least 4 to satisfy diversity requirements")

    lower = string.ascii_lowercase
    upper = string.ascii_uppercase
    digits = string.digits
    special = "!@#$%^&*()-_=+[]{}|;:,.<>?"
    all_chars = lower + upper + digits + special

    classes = [lower, upper, digits, special]

    # Guarantee one character from each class
    result = [secrets.choice(cls) for cls in classes]

    # Fill remaining positions from all characters
    result.extend(secrets.choice(all_chars) for _ in range(length - len(classes)))

    # Shuffle to avoid predictable class positions
    secrets.SystemRandom().shuffle(result)

    return "".join(result)


def _get_secret_credentials(secret_name: str, namespace: str) -> tuple[str, str]:
    """Retrieve username and password from a Kubernetes Secret.

    Args:
        secret_name: Name of the Secret
        namespace: Kubernetes namespace

    Returns:
        Tuple of (username, password)

    Raises:
        subprocess.CalledProcessError: If kubectl fails
        ValueError: If Secret data is missing or malformed
    """
    cmd = ["kubectl", "get", "secret", secret_name, "-n", namespace, "-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    secret = json.loads(result.stdout)
    data = secret.get("data", {})

    username_b64 = data.get("username")
    password_b64 = data.get("password")

    if not username_b64:
        raise ValueError(f"Secret {secret_name} missing 'username' key")
    if not password_b64:
        raise ValueError(f"Secret {secret_name} missing 'password' key")

    username = base64.b64decode(username_b64).decode()
    password = base64.b64decode(password_b64).decode()

    return username, password


def _get_keycloak_admin_token(
    keycloak_url: str,
    username: str,
    password: str,
    insecure: bool = False,
    ca_bundle: Path | None = None,
) -> str:
    """Get an admin access token from Keycloak's master realm.

    Admin tokens are always obtained from the master realm, regardless of the target realm.

    Args:
        keycloak_url: Base URL of the Keycloak server
        username: Admin username
        password: Admin password
        insecure: Disable TLS certificate verification
        ca_bundle: Path to a custom CA certificate bundle

    Returns:
        Admin access token

    Raises:
        httpx.HTTPError: If the token request fails
        ValueError: If the response is missing the access_token
    """
    if insecure:
        verify: bool | str = False
    elif ca_bundle is not None:
        verify = str(ca_bundle)
    else:
        verify = True

    token_url = f"{keycloak_url}/realms/master/protocol/openid-connect/token"

    data = {
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": username,
        "password": password,
    }

    with httpx.Client(timeout=30.0, verify=verify) as client:
        resp = client.post(token_url, data=data)
        resp.raise_for_status()

        result = resp.json()
        access_token = result.get("access_token")

        if not access_token:
            raise ValueError("access_token missing from token response")

        return access_token


def _find_keycloak_user_id(
    client: httpx.Client,
    users_url: str,
    username: str,
    headers: dict[str, str],
) -> str | None:
    """Search for a Keycloak user by username and return their ID.

    Args:
        client: httpx.Client instance
        users_url: Keycloak users endpoint URL
        username: Username to search for (exact match)
        headers: Request headers (must include Authorization)

    Returns:
        The user ID string, or None if the user was not found or the search failed
    """
    search_params = {"username": username, "exact": "true"}
    resp = client.get(users_url, params=search_params, headers=headers)

    if resp.status_code != 200:
        return None

    users = resp.json()
    if not users:
        return None

    return users[0].get("id")


def _create_keycloak_user(
    keycloak_url: str,
    realm: str,
    token: str,
    username: str,
    password: str,
    insecure: bool = False,
    ca_bundle: Path | None = None,
) -> None:
    """Create a user in Keycloak, or reset their password if they already exist.

    Resetting the password when the user exists ensures the K8s secret (written after
    this call) always matches the actual Keycloak credentials.

    Args:
        keycloak_url: Base URL of the Keycloak server
        realm: Keycloak realm name
        token: Admin access token
        username: Username for the user
        password: Password for the user
        insecure: Disable TLS certificate verification
        ca_bundle: Path to a custom CA certificate bundle

    Raises:
        httpx.HTTPError: If Keycloak API requests fail
    """
    if insecure:
        verify: bool | str = False
    elif ca_bundle is not None:
        verify = str(ca_bundle)
    else:
        verify = True

    with httpx.Client(timeout=30.0, verify=verify) as client:
        users_url = f"{keycloak_url}/admin/realms/{realm}/users"
        headers = {"Authorization": f"Bearer {token}"}

        # Check if user already exists
        user_id = _find_keycloak_user_id(client, users_url, username, headers)

        if user_id is not None:
            print(f"User already exists in Keycloak, resetting password: {username}")
            _reset_keycloak_user_password(keycloak_url, realm, token, user_id, password, client)
            return

        # Create user with password
        user_payload = {
            "username": username,
            "enabled": True,
            "emailVerified": True,
            "credentials": [
                {
                    "type": "password",
                    "value": password,
                    "temporary": False,
                }
            ],
        }

        create_resp = client.post(users_url, json=user_payload, headers=headers)

        if create_resp.status_code == 201:
            print(f"User created successfully: {username}")
            return

        if create_resp.status_code == 409:
            # User exists (possibly created concurrently)
            print(
                f"User already exists (409 on create), re-searching to reset password: {username}"
            )
            user_id = _find_keycloak_user_id(client, users_url, username, headers)
            if not user_id:
                raise ValueError("Could not find user after 409 conflict")

            _reset_keycloak_user_password(keycloak_url, realm, token, user_id, password, client)
            return

        create_resp.raise_for_status()


def _reset_keycloak_user_password(
    keycloak_url: str,
    realm: str,
    token: str,
    user_id: str,
    password: str,
    client: httpx.Client,
) -> None:
    """Set a user's password via the Keycloak admin API.

    Args:
        keycloak_url: Base URL of the Keycloak server
        realm: Keycloak realm name
        token: Admin access token
        user_id: Keycloak user ID
        password: New password
        client: httpx.Client instance

    Raises:
        httpx.HTTPError: If the password reset fails
    """
    reset_url = f"{keycloak_url}/admin/realms/{realm}/users/{user_id}/reset-password"
    payload = {
        "type": "password",
        "value": password,
        "temporary": False,
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    resp = client.put(reset_url, json=payload, headers=headers)

    if resp.status_code != 204:
        raise httpx.HTTPStatusError(
            f"Reset password failed with status {resp.status_code}: {resp.text}",
            request=resp.request,
            response=resp,
        )


def _create_credentials_secret(username: str, password: str, namespace: str) -> None:
    """Create a K8s secret with test user credentials.

    Args:
        username: Username
        password: Password
        namespace: Kubernetes namespace

    Raises:
        subprocess.CalledProcessError: If kubectl fails
    """
    secret_spec = _build_secret_spec(
        name=_VIP_TEST_CREDENTIALS_SECRET,
        namespace=namespace,
        data_dict={
            "VIP_TEST_USERNAME": base64.b64encode(username.encode()).decode(),
            "VIP_TEST_PASSWORD": base64.b64encode(password.encode()).decode(),
        },
        labels_dict={
            "app.kubernetes.io/managed-by": "vip",
            "app.kubernetes.io/name": "vip-verify",
        },
    )

    secret_json = json.dumps(secret_spec)

    cmd = ["kubectl", "apply", "-f", "-", "-n", namespace]
    subprocess.run(
        cmd,
        input=secret_json,
        capture_output=True,
        text=True,
        check=True,
    )
