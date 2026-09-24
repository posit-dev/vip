"""Module-level mutable state shared by the VIP plugin submodules.

Each variable has exactly one owner, this module. Every reader and writer
goes through ``state.<name>`` so a value set in one submodule is seen by
the others; ``from vip.plugin.state import X`` would copy the value at
import time instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from vip.plugin.terminal import _Heartbeat

# Module-level reference to the active pytest.Config, set in pytest_configure.
# Safe because pytester runs in a subprocess (fresh import each time).
_active_config: pytest.Config | None = None

# Color of the result line currently being rendered, set in
# pytest_runtest_logreport (tryfirst, so it lands before the terminal reporter
# renders the same report).  Consumed by the progress-indicator recolor wrapper
# installed on the terminal reporter.  ``None`` means "fall back to pytest's
# default color".  Module-level is safe: this only matters in a single,
# non-xdist process (see _install_progress_recolor).
_current_line_color: str | None = None

# Exposed so that code importing gevent/locust (which calls monkey.patch_all)
# can stop the heartbeat thread first to avoid a deadlock.
_current_heartbeat: _Heartbeat | None = None
