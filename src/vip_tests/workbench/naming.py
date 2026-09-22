"""Worker-scoped Workbench session names.

The worker id these embed is what cleanup parses back out (see
:func:`~vip.clients.workbench.session_owner`), so the formats must stay in step
with ``_VIP_OWNER_PATTERNS`` in ``vip/clients/workbench.py``.
"""

from __future__ import annotations

import os
import time


def current_worker_id() -> str:
    """Return this process's xdist worker id (``"main"`` when running serially).

    Session names embed this so cleanup can tell a worker's own sessions from a
    sibling worker's (see :func:`~vip.clients.workbench.session_owner`).
    """
    return os.environ.get("PYTEST_XDIST_WORKER", "main")


def vip_session_prefix(kind: str) -> str:
    """Build a ``_vip_<kind>_<worker>_<ts>_`` session-name prefix.

    Some scenarios name sessions outside :func:`unique_session_name` (they carry
    a profile or an index rather than a source file), but the contract is the
    same: the worker id must be in the name so cleanup can attribute the session
    back to the worker that made it (see
    :func:`~vip.clients.workbench.session_owner`) and not quit a sibling
    worker's live sessions.  The timestamp keeps names clear of leftovers from
    previous runs.

    Route every such scheme through this one helper.  A prefix built by hand
    that omits the worker segment is unowned, and unowned means no in-run sweep
    will clean it up -- the session leaks for the rest of the run.  Computed per
    call, not at import time, so the worker id is read after xdist has set it.
    """
    return f"_vip_{kind}_{current_worker_id()}_{int(time.time())}_"


def capacity_session_prefix() -> str:
    """Prefix for this worker's resource-profile capacity session names."""
    return vip_session_prefix("cap")


def k8s_session_prefix() -> str:
    """Prefix for this worker's Kubernetes capacity session names."""
    return vip_session_prefix("k8s")


def unique_session_name(filename: str) -> str:
    """Generate a Workbench session name unique across xdist workers.

    Session tests look up rows via aria-label locators. Using only
    ``int(time.time())`` collided across workers that entered the same
    second, producing strict-mode failures once locators were tightened
    to ends-with matches. Worker id + nanosecond timestamp guarantees
    uniqueness for any practical parallelism.

    The worker id is not just for uniqueness: cleanup parses it back out to
    scope its sweeps, so the format must stay parseable by
    :func:`~vip.clients.workbench.session_owner`.
    """
    return f"VIP {filename} - {current_worker_id()}-{time.time_ns()}"
