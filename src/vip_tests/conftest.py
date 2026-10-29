"""Root conftest for VIP's own product tests.

VIP's core fixtures (``vip_config``, ``connect_client``, etc.) and shared BDD
step definitions live in ``src/vip/fixtures.py``, registered by
``vip.plugin.pytest_configure`` as its own pytest plugin -- see that module's
docstring. pytest scopes ``conftest.py`` fixtures by directory ancestry, so
defining them here would make them invisible to any test collected outside
``src/vip_tests``, including every extension directory loaded via
``--vip-extensions`` (issue #609).

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
- Connect content-cleanup fixtures. Two are ``autouse=True`` and run for
  every test in this package. They only request an API client when an API
  key or registered client-auth provider is available, so unauthenticated
  checks can run without initializing an authenticated client. Keeping them
  directory-scoped avoids adding product cleanup to unrelated pytest runs.
  Extension directories do not get automatic cleanup; extension authors
  must provide their own fixture or call ``connect_client.cleanup_content``.
"""

from __future__ import annotations

import logging

import pytest

from vip.client_auth import get_client_auth_factory
from vip.errors import ProductUnreachableError

logger = logging.getLogger(__name__)

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
# ``_connect_cleanup_client is None`` so unauthenticated checks and runs
# without Connect do not initialize an authenticated client.  Deliberately NOT part of
# vip.fixtures/vip.plugin -- see the module docstring above.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _connect_created_guids():
    """Append-only record of content GUIDs created this run (tag-independent)."""
    return []


@pytest.fixture(scope="session")
def _connect_cleanup_client(request, vip_config):
    """Only initialize cleanup when Connect authentication is available."""
    if not vip_config.connect.is_configured:
        return None
    if not vip_config.connect.api_key and get_client_auth_factory(vip_config.auth.idp) is None:
        return None
    return request.getfixturevalue("connect_client")


@pytest.fixture(autouse=True)
def _connect_content_cleanup(_connect_cleanup_client, _connect_created_guids):
    """Delete content created during this test, on pass or fail."""
    start = len(_connect_created_guids)
    yield
    if _connect_cleanup_client is None:
        return
    created = _connect_created_guids[start:]
    if created:
        _connect_cleanup_client.cleanup_content(created)


@pytest.fixture(scope="session", autouse=True)
def _connect_end_of_run_sweep(_connect_cleanup_client, _connect_created_guids):
    """End-of-run safety net: delete tracked GUIDs, then tag-based cross-run sweep.

    The tag-based sweep now raises :class:`ProductUnreachableError` on a failed
    tag lookup instead of silently reporting "nothing to clean up" (see
    ``ConnectClient.cleanup_vip_content``). This is a best-effort safety net
    running at teardown, not an assertion under test, so a transient API
    failure here is logged and swallowed rather than turning an otherwise
    green run into a teardown error.
    """
    yield
    if _connect_cleanup_client is None:
        return
    if _connect_created_guids:
        _connect_cleanup_client.cleanup_content(_connect_created_guids)
    try:
        _connect_cleanup_client.cleanup_vip_content()
    except ProductUnreachableError:
        logger.warning(
            "end-of-run Connect content sweep could not reach the tag API", exc_info=True
        )
