"""Hold a scenario until every other xdist worker in the run has finished.

Workbench sign-out revokes every auth cookie the account holds, so under a shared auth session
it must not run while another worker still uses that session. A separate xdist group only queues
it last: xdist hands it to the first free worker while the others finish their own groups. Each
worker therefore drops a marker when its session ends, and the sign-out scenario waits for them.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

SIGNOUT_BARRIER_TIMEOUT = float(os.environ.get("VIP_SIGNOUT_BARRIER_TIMEOUT", "1800"))

_DONE_DIR_NAME = "vip-workers-done"


def _done_dir(config: pytest.Config) -> Path | None:
    """The run-wide marker directory, or None outside an xdist worker.

    xdist gives each worker ``basetemp = <controller basetemp>/popen-gw<N>``, so the parent is
    shared by this run's workers only, and pytest prunes it with the rest of old basetemps.
    """
    basetemp = config.option.basetemp
    if not basetemp or "PYTEST_XDIST_WORKER" not in os.environ:
        return None
    return Path(basetemp).parent / _DONE_DIR_NAME


def mark_worker_done(config: pytest.Config) -> None:
    """Record that this worker has run all its tests and torn down its fixtures."""
    done_dir = _done_dir(config)
    if done_dir is None:
        return
    done_dir.mkdir(exist_ok=True)
    (done_dir / os.environ["PYTEST_XDIST_WORKER"]).touch()


def wait_for_other_workers(
    config: pytest.Config, timeout: float, *, poll_interval: float = 2.0
) -> list[str]:
    """Block until every other worker has called :func:`mark_worker_done`.

    Returns the workers still running when *timeout* expired (empty on success, and always
    empty in a serial run or with one worker). A worker xdist replaced after a crash never
    reports, so the wait then runs to the timeout.
    """
    done_dir = _done_dir(config)
    count = int(os.environ.get("PYTEST_XDIST_WORKER_COUNT", "1"))
    if done_dir is None or count <= 1:
        return []
    others = {f"gw{i}" for i in range(count)} - {os.environ["PYTEST_XDIST_WORKER"]}
    deadline = time.monotonic() + timeout
    while True:
        done = {p.name for p in done_dir.iterdir()} if done_dir.is_dir() else set()
        waiting = sorted(others - done)
        if not waiting or time.monotonic() >= deadline:
            return waiting
        time.sleep(poll_interval)
