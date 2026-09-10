"""Example custom test - extend VIP with site-specific checks.

Place this file (and its .feature file) in a directory, then configure VIP to
include it:

    [general]
    extension_dirs = ["/path/to/custom_tests"]

Or on the command line:

    vip verify --config vip.toml --extensions /path/to/custom_tests

This is the "minimal" scaffold template. It checks the Connect deployment
you already have configured, via VIP's own ``connect_client`` fixture, rather
than a hardcoded external address -- so the first run of a new extension
exercises the product you are actually validating and needs no outbound
internet access.

Reach for the VIP fixtures rather than calling ``httpx`` yourself. A bare
``httpx.get()`` ignores the TLS and proxy settings VIP is configured with
(``[tls] insecure``/``ca_bundle`` and the ``[proxy]`` block), so a test written
that way fails against a deployment behind a private CA or a proxy-only
network -- exactly the environments VIP exists to validate. ``connect_client``
carries all of that already.

Custom tests have full access to VIP fixtures (vip_config, connect_client,
etc. -- see AGENTS.md for the full list) and can use any pytest-bdd or
Playwright features.
"""

from __future__ import annotations

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


@when("I request the custom endpoint", target_fixture="custom_status")
def request_endpoint(connect_client):
    # `connect_client` is a VIP core fixture (defined in src/vip/fixtures.py)
    # that hands you an authenticated httpx wrapper pointed at the Connect
    # deployment configured in vip.toml -- already carrying your proxy, CA
    # bundle and insecure settings. Using it instead of building your own
    # request means this test checks *your* deployment, the same way VIP's
    # own tests reach it.
    #
    # `.health()` returns the HTTP status of Connect's server-settings
    # endpoint. Swap in whichever call your check needs; the client exposes
    # named methods (`server_settings()`, `current_user()`, ...) rather than a
    # generic get.
    #
    # `target_fixture="custom_status"` is pytest-bdd's mechanism for passing
    # this step's return value to the `then` step below as a fixture named
    # `custom_status`, instead of stashing it in a module-level global.
    return connect_client.health()


@then("it responds successfully")
def responds_ok(custom_status):
    assert custom_status < 400, f"Custom endpoint returned HTTP {custom_status}"
