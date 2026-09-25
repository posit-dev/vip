"""VIP pytest plugin.

Registered via the ``pytest11`` entry point so it activates automatically
when the ``vip`` package is installed.

Responsibilities:
- Register custom markers.
- Add CLI options (``--vip-config``, ``--vip-extensions``, ``--vip-report``,
  ``--interactive-auth``).
- Deselect (exclude) tests whose product is not configured.
- Auto-skip tests whose product version doesn't meet ``min_version``.
- Ensure prerequisites run before other tests.
- Collect extension directories.
- Write a JSON results file for the Quarto report.
- Handle interactive OIDC authentication for external identity providers.

pytest registers this package module as the plugin and only discovers the
``pytest_*`` hooks bound here, so every hook implementation is re-exported
below; the submodules themselves are never registered. The namespace also
re-exports every other name imported from ``vip.plugin``. Patch a helper on
the submodule that calls it, not here: a re-export does not change the
global the submodule looks up. Mutable module-level state lives in
``vip.plugin.state`` and is deliberately not re-exported, since a re-export
would be a frozen copy.
"""

from vip.plugin.auth import _restore_worker_auth
from vip.plugin.configure import pytest_configure, pytest_configure_node, pytest_sessionstart
from vip.plugin.options import pytest_addoption
from vip.plugin.results import (
    EXIT_UNPROVEN,
    _classify_skip_reason,
    _control_marker_names,
    _emit_extra_formats,
    _extract_exception_info,
    _extract_skip_reason,
    _format_concise_error,
    pytest_runtest_logreport,
    pytest_runtest_makereport,
    pytest_sessionfinish,
)
from vip.plugin.selection import pytest_bdd_apply_tag, pytest_collection_modifyitems
from vip.plugin.terminal import (
    _Heartbeat,
    _outcome_color,
    _shorten_location_line,
    pytest_runtest_logstart,
    pytest_runtest_protocol,
)
from vip.stash import _auth_mode_key, _auth_session_key, _vip_config_key

__all__ = [
    "EXIT_UNPROVEN",
    "_Heartbeat",
    "_auth_mode_key",
    "_auth_session_key",
    "_classify_skip_reason",
    "_control_marker_names",
    "_emit_extra_formats",
    "_extract_exception_info",
    "_extract_skip_reason",
    "_format_concise_error",
    "_outcome_color",
    "_restore_worker_auth",
    "_shorten_location_line",
    "_vip_config_key",
    "pytest_addoption",
    "pytest_bdd_apply_tag",
    "pytest_collection_modifyitems",
    "pytest_configure",
    "pytest_configure_node",
    "pytest_runtest_logreport",
    "pytest_runtest_logstart",
    "pytest_runtest_makereport",
    "pytest_runtest_protocol",
    "pytest_sessionfinish",
    "pytest_sessionstart",
]
