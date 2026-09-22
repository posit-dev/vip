"""Pytest ``config.stash`` keys shared across VIP's plugin and fixtures.

Lives on its own, outside both ``vip.plugin`` and ``vip.fixtures``, so both
modules can import it without creating a cycle: ``vip.plugin`` registers
``vip.fixtures`` as a pytest plugin (see ``vip.fixtures``'s module docstring),
and ``vip.fixtures`` needs these keys to read what ``vip.plugin`` stashed.
This module also can't live inside the future ``vip/plugin/`` package --
importing ``vip.plugin.stash`` would execute ``vip/plugin/__init__.py``
first, bringing the cycle right back.
"""

from __future__ import annotations

from typing import Any

import pytest

from vip.config import VIPConfig

_vip_config_key = pytest.StashKey[VIPConfig]()
_ext_dirs_key = pytest.StashKey[list[str]]()
_results_key = pytest.StashKey[list[dict[str, Any]]]()
_auth_session_key = pytest.StashKey[Any]()
_auth_mode_key = pytest.StashKey[str]()
_version_na_key = pytest.StashKey[bool]()
# Wall-clock start of the session, for the "run_duration_seconds" provenance
# field. Recorded in every process (worker or controller) but only read back
# on the controller in pytest_sessionfinish, which is the process that
# ultimately writes results.json.
_session_start_key = pytest.StashKey[float]()
_scenario_stash_key = pytest.StashKey[dict[str, str | None]]()
