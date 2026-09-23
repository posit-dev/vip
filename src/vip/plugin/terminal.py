"""Terminal display: per-line progress recoloring, location shortening, the
long-running test heartbeat, and xdist logstart suppression.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Generator
from typing import Any

import pytest

from vip.plugin import state


def _outcome_color(report: pytest.TestReport) -> str | None:
    """Return the pytest markup color for a single result line's outcome.

    Mirrors pytest's own per-letter markup (see
    ``TerminalReporter.pytest_runtest_logreport``): green for a plain pass,
    yellow for xfail/xpass/skip, red for a failure or error.  Returns ``None``
    for the setup/teardown phases and any outcome we don't recolor, so the
    caller falls back to pytest's default (cumulative) color.

    Only the ``call`` phase — plus a ``setup`` that skipped, which is how an
    ordinary skip surfaces — carries a line the user sees, so other phases are
    ignored to avoid recoloring a percentage that belongs to a passing test.
    """
    if report.when not in ("call", "setup"):
        return None
    if report.when == "setup" and not report.skipped:
        return None
    if report.failed:
        return "red"
    if report.skipped or hasattr(report, "wasxfail"):
        return "yellow"
    if report.passed:
        return "green"
    return None


def _install_progress_recolor(config: pytest.Config) -> None:
    """Color each line's trailing progress indicator by that line's outcome.

    pytest colors the ``[ 42%]`` progress indicator with the session's
    *cumulative* "main color": once any test fails, ``_get_main_color`` returns
    red and every subsequent line's indicator is red too — making a run look far
    more broken than it is.  We want only the failing line's indicator red.

    ``_write_progress_information_filling_space`` reads the color from
    ``self._get_main_color()``.  We wrap it to temporarily swap in the color of
    the line just reported (captured in ``pytest_runtest_logreport``), then
    restore the real one so the end-of-session summary still uses pytest's
    cumulative color.

    Skipped under xdist: the controller renders progress on its own
    ``pytest_runtest_logreport`` path (the ``running_xdist`` branch), which uses
    a fixed cyan indicator and never calls the wrapped method, so there is
    nothing to recolor and the module-level ``_current_line_color`` would race
    across workers besides.
    """
    if config.getoption("--vip-verbose", default=False):
        return
    if hasattr(config, "workerinput"):
        return
    tr = config.pluginmanager.get_plugin("terminalreporter")
    if tr is None:
        return

    original_fill = tr._write_progress_information_filling_space
    original_get_main_color = tr._get_main_color

    def recolored_fill(*args: Any, **kwargs: Any) -> Any:
        if state._current_line_color is None:
            return original_fill(*args, **kwargs)
        # Swap _get_main_color to report this line's color, then restore it so
        # nothing else (summary line, past-edge writes) is affected.
        known = original_get_main_color()[1]
        tr._get_main_color = lambda: (state._current_line_color, known)
        try:
            return original_fill(*args, **kwargs)
        finally:
            tr._get_main_color = original_get_main_color

    tr._write_progress_information_filling_space = recolored_fill


# The installed test package root.  pytest node paths are "/"-normalized
# (see _pytest.terminal._locationline), so the marker uses a forward slash on
# every platform.
_TEST_PKG_MARKER = "vip_tests/"


def _shorten_location_line(line: str) -> str:
    """Drop the install-path prefix from a pytest ``-v`` location line.

    ``vip verify`` runs pytest with ``-v``, so every result line is prefixed
    with the node's path.  When VIP is installed as a tool that path is the
    long site-packages location, e.g.::

        ../../../.local/share/uv/tools/posit-vip/lib/python3.13/site-packages/vip_tests/connect/test_auth.py::test_connect_login_ui

    Keeping only the portion after the ``vip_tests/`` package root puts the
    meaningful part first::

        connect/test_auth.py::test_connect_login_ui

    Lines without the marker (e.g. user extension tests collected from an
    arbitrary directory) are returned unchanged.  Uses ``rfind`` so a marker
    substring appearing earlier in an install path never wins over the real
    package root.
    """
    idx = line.rfind(_TEST_PKG_MARKER)
    if idx == -1:
        return line
    return line[idx + len(_TEST_PKG_MARKER) :]


def _install_location_shortener(config: pytest.Config) -> None:
    """Wrap the terminal reporter's ``_locationline`` to truncate node paths.

    Only active in concise (non-``--vip-verbose``) mode.  There is no public
    hook for the per-test location string, so we wrap the bound method on the
    registered reporter instance.  Under xdist this runs on the controller,
    which is where result lines are rendered, so worker output is covered too.
    """
    if config.getoption("--vip-verbose", default=False):
        return
    tr = config.pluginmanager.get_plugin("terminalreporter")
    if tr is None:
        return
    original = tr._locationline

    def shortened(*args: Any, **kwargs: Any) -> str:
        return _shorten_location_line(original(*args, **kwargs))

    tr._locationline = shortened


# ---------------------------------------------------------------------------
# Long-running test heartbeat
# ---------------------------------------------------------------------------

_HEARTBEAT_INTERVAL = 30  # seconds between "still running" messages


class _Heartbeat:
    """Print periodic elapsed-time messages while a test is running."""

    def __init__(self, writer, interval: int = _HEARTBEAT_INTERVAL):
        self._writer = writer
        self._interval = interval
        self._start: float = 0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._start = time.monotonic()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        # Join without a timeout: callers (notably before locust/gevent import)
        # rely on no heartbeat thread being alive, and _run exits promptly once
        # the stop event is set.
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval):
            elapsed = int(time.monotonic() - self._start)
            self._writer(f"  ... still running ({elapsed}s)")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem) -> Generator[None, None, None]:  # noqa: ARG001
    """Print periodic heartbeat messages while a test is running."""
    heartbeat: _Heartbeat | None = None
    if state._active_config is not None:
        tr = state._active_config.pluginmanager.get_plugin("terminalreporter")
        if tr is not None:
            heartbeat = _Heartbeat(tr.write_line)
            heartbeat.start()
            state._current_heartbeat = heartbeat
    try:
        yield
    finally:
        if heartbeat is not None:
            heartbeat.stop()
            state._current_heartbeat = None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_logstart(
    nodeid: str,  # noqa: ARG001
    location: tuple[str, int | None, str],  # noqa: ARG001
) -> Generator[None, None, None]:
    """Suppress the built-in terminal reporter's pre-test location line under xdist.

    Under real xdist parallelism, the controller relays each worker's
    ``pytest_runtest_logstart`` event (via ``dsession.worker_logstart``) the
    moment that worker *starts* a test, independent of when any other
    worker's test *finishes*. pytest's built-in ``TerminalReporter`` assumes
    a single serial stream: at ``-v`` it writes the location at logstart and
    later appends the outcome to that *same* line at logreport (matched via
    a shared ``currentfspath`` attribute). With several workers running
    concurrently, multiple tests' logstart events land before any of their
    logreport events, so ``currentfspath`` gets overwritten by other tests'
    locations before the original one's outcome arrives -- producing a
    location-only line up front and a disconnected result line later.

    We already delete ``report.node`` below so ``pytest_runtest_logreport``
    takes its non-xdist branch and writes location + outcome together, in
    one line, in a single call (see that hook's docstring). That only
    produces one line if nothing has already claimed the location line
    first. So here, only when the xdist controller is actually distributing
    (``dsession`` registered, and this isn't a worker), we suppress the
    logstart write for the duration of the wrapped call.

    The built-in reporter gates that write on ``showlongtestinfo``, which
    reads the fine-grained ``verbosity_test_cases`` *ini* value rather than
    the plain ``-v`` count whenever that ini value isn't ``"auto"`` -- and
    ``pytest_configure`` above already pins it (via ``config._inicache``) to
    force skip reasons to print in full. So bumping ``config.option.verbose``
    here would have no effect; we instead override that same ini-cache entry
    to ``"0"``, restoring it immediately after so the later
    ``pytest_runtest_logreport`` call (which reads the same cached value to
    decide whether to show the outcome line at all) is unaffected. Nothing
    else runs in between, since hookwrapper dispatch is synchronous.
    """
    config = state._active_config
    if (
        config is None
        or hasattr(config, "workerinput")
        or not config.pluginmanager.hasplugin("dsession")
    ):
        yield
        return

    original = config._inicache.get("verbosity_test_cases")
    config._inicache["verbosity_test_cases"] = "0"
    try:
        yield
    finally:
        if original is None:
            config._inicache.pop("verbosity_test_cases", None)
        else:
            config._inicache["verbosity_test_cases"] = original
