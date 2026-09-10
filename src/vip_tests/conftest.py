"""Root conftest for VIP's own product tests.

VIP's core fixtures (``vip_config``, ``connect_client``, etc.) and shared BDD
step definitions used to live in this file. They moved to
``src/vip/fixtures.py``, registered by ``vip.plugin.pytest_configure`` as its
own pytest plugin -- see that module's docstring. pytest scopes
``conftest.py`` fixtures by directory ancestry, so keeping them here made them
invisible to any test collected outside ``src/vip_tests``, including every
extension directory loaded via ``--vip-extensions`` (issue #609).

This file intentionally does not re-export those names: a session-scoped
fixture like ``connect_client`` must resolve to exactly one ``FixtureDef`` for
the whole run, or a run that collects ``src/vip_tests`` alongside an extension
directory (what ``vip verify`` does) would build two independent
``ConnectClient`` instances -- and two independent browser auth sessions --
instead of sharing one.

What *does* stay here:

- Warning-filter scoping that must apply only to VIP's own test package, not
  everywhere ``vip`` is installed (unlike the filters in
  ``vip.plugin.pytest_configure``, which are meant to be global).
- The three Connect content-cleanup fixtures below. Two of them are
  ``autouse=True``, which -- unlike an ordinary fixture a test has to request
  -- runs for every test collected in a session, unconditionally. Registering
  them as part of ``vip.fixtures`` (a global plugin, active in *any* pytest
  session where ``vip`` is installed) would make every such run pay for
  Connect-content bookkeeping it never asked for, and worse: a project with
  its own unrelated ``vip.toml`` that configures ``[connect]`` without an API
  key (for reasons that have nothing to do with VIP's product tests) would
  have every one of its tests fail in setup, because
  ``_connect_content_cleanup`` requests ``connect_client``, which calls
  ``require_connect_api_key`` and fails loudly whenever Connect is configured
  but unauthenticated. Keeping these three fixtures directory-scoped here
  means they still apply throughout ``src/vip_tests``, but leave any run that
  never touches this package alone. The consequence: extension directories do
  not get automatic Connect-content cleanup -- a real, known gap, not an
  oversight. An extension author who creates Connect content today has to
  clean it up the same way any pytest-bdd test outside VIP would: with its
  own fixture, or by calling ``connect_client.cleanup_content(...)`` directly.
"""

from __future__ import annotations

import pytest

# pytest-bdd step definitions with target_fixture return values intentionally;
# pytest 9.x warns about non-None returns from test functions. Scoped to
# vip_tests only so selftests still catch accidental returns. This has to
# stay a conftest.py pytestmark (directory-scoped) rather than move into
# vip.fixtures: that module is registered as a global plugin, and a global
# filter here would just as happily suppress the warning in selftests that
# exist to catch it.
pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestReturnNotNoneWarning")


# ---------------------------------------------------------------------------
# Connect content cleanup — promoted from connect/conftest.py so that any
# package (workbench, cross_product, …) that creates Connect content can
# register GUIDs into the shared tracking list.  The fixtures guard against
# ``connect_client is None`` so they are safe to activate in workbench-only
# runs where Connect is not configured.  Deliberately NOT part of
# vip.fixtures/vip.plugin -- see the module docstring above.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _connect_created_guids():
    """Append-only record of content GUIDs created this run (tag-independent)."""
    return []


@pytest.fixture(autouse=True)
def _connect_content_cleanup(connect_client, _connect_created_guids):
    """Delete content created during this test, on pass or fail."""
    start = len(_connect_created_guids)
    yield
    if connect_client is None:
        return
    created = _connect_created_guids[start:]
    if created:
        connect_client.cleanup_content(created)


@pytest.fixture(scope="session", autouse=True)
def _connect_end_of_run_sweep(connect_client, _connect_created_guids):
    """End-of-run safety net: delete tracked GUIDs, then tag-based cross-run sweep."""
    yield
    if connect_client is None:
        return
    if _connect_created_guids:
        connect_client.cleanup_content(_connect_created_guids)
    connect_client.cleanup_vip_content()
