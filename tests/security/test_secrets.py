"""Step definitions for secrets and token storage tests."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from pytest_bdd import scenario, given, when, then


@scenario("test_secrets.feature", "API keys are not stored in the VIP config file")
def test_no_plaintext_secrets():
    pass


@scenario("test_secrets.feature", "Connect API key is provided via environment variable")
def test_api_key_from_env():
    pass


@given("a VIP configuration file is in use", target_fixture="config_path")
def config_file_exists(request):
    config_option = request.config.getoption("--vip-config", default=None)
    if config_option:
        p = Path(config_option)
    else:
        p = Path("vip.toml")
    if not p.exists():
        pytest.skip("No VIP configuration file found")
    return p


@when("I inspect the configuration file contents", target_fixture="config_text")
def read_config(config_path):
    return config_path.read_text()


@then("no plaintext API keys or passwords are present in the file")
def no_plaintext_secrets(config_text):
    # Look for uncommented lines with api_key = "..." or password = "..."
    # that contain actual values (not placeholders).
    risky = re.findall(
        r'^(?!\s*#)\s*(api_key|password)\s*=\s*"(.+?)"',
        config_text,
        re.MULTILINE,
    )
    # Filter out obvious placeholder values.
    placeholders = {"...", "your-api-key", "changeme", ""}
    real_secrets = [(k, v) for k, v in risky if v not in placeholders]
    assert not real_secrets, (
        f"Plaintext secrets found in config file: {[k for k, _ in real_secrets]}. "
        "Use environment variables instead."
    )


@given("Connect is configured with an API key")
def connect_has_key(vip_config):
    if not vip_config.connect.api_key:
        pytest.skip("Connect API key is not set")


@then("the API key was loaded from the VIP_CONNECT_API_KEY environment variable")
def key_from_env():
    env_key = os.environ.get("VIP_CONNECT_API_KEY", "")
    assert env_key, (
        "VIP_CONNECT_API_KEY environment variable is not set. "
        "Secrets should be provided via environment variables, not the config file."
    )
