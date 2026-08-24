"""Example custom test - extend VIP with site-specific checks.

Place this file (and its .feature file) in a directory, then configure VIP to
include it:

    [general]
    extension_dirs = ["/path/to/custom_tests"]

Or on the command line:

    vip verify --config vip.toml --extensions /path/to/custom_tests

This is the "minimal" scaffold template. It checks the Connect deployment
you already have configured (via the ``connect_url`` fixture from VIP core)
rather than a hardcoded external address, so the very first run of a new
extension exercises the product you are actually validating and needs no
outbound internet access.

Custom tests have full access to VIP fixtures (vip_config, connect_client,
etc. -- see AGENTS.md for the full list) and can use any pytest-bdd or
Playwright features.
"""

from __future__ import annotations

import httpx
import pytest
from pytest_bdd import given, scenario, then, when


# `@pytest.mark.connect` on the `@scenario` function is what makes VIP's
# auto-skip work at the pytest level: when Connect isn't configured, this
# test is deselected instead of erroring out with nothing to talk to. The
# `.feature` file's `@connect` tag does the same thing for pytest-bdd's own
# collection, but VIP's deselection logic (`vip.plugin`) checks pytest
# markers, so both are kept in sync deliberately -- omitting either is the
# single most common mistake when writing a new extension.
@pytest.mark.connect
@scenario("test_custom_check.feature", "Custom endpoint responds successfully")
def test_custom_health():
    pass


@given("I have a custom endpoint to verify")
def have_endpoint():
    # Nothing to set up here -- the endpoint itself comes from VIP's own
    # configuration (see the `when` step below). Replace this with your own
    # precondition logic if your check needs one (e.g. asserting a feature
    # flag or config value is set before proceeding).
    pass


@when("I request the custom endpoint", target_fixture="custom_response")
def request_endpoint(connect_url):
    # `connect_url` is a VIP core fixture (defined in src/vip_tests/conftest.py)
    # that resolves to the Connect URL configured in vip.toml. Using it
    # instead of a constant means this test always checks *your* deployment.
    #
    # `/server_settings` is Connect's unauthenticated health endpoint, so this
    # check needs no API key -- a good fit for a "first extension you run"
    # template. Swap in your own endpoint and, if it needs auth, the
    # `connect_client` fixture (an authenticated httpx wrapper) instead.
    #
    # `target_fixture="custom_response"` is pytest-bdd's mechanism for passing
    # this step's return value to the `then` step below as a fixture named
    # `custom_response`, instead of stashing it in a module-level global.
    url = f"{connect_url}/__api__/server_settings"
    try:
        return httpx.get(url, timeout=15)
    except Exception as exc:
        pytest.fail(f"Could not reach {url}: {exc}")


@then("it responds successfully")
def responds_ok(custom_response):
    assert custom_response.status_code < 400, (
        f"Custom endpoint returned HTTP {custom_response.status_code}"
    )
