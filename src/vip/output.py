"""Terminal output for the VIP CLI and the code it drives.

This is the only module that writes to stdout or stderr. Command results (data a
caller might pipe) go through :func:`out`; progress, warnings, errors and
diagnostics go to stderr through :func:`info`, :func:`warn`, :func:`error` and
:func:`debug`. Messages are written exactly as given, with no added prefix.
"""

from __future__ import annotations

import enum
import logging
import os
import sys
from typing import TextIO

VERBOSITY_ENV_VAR = "VIP_VERBOSITY"

_LOGGER_NAME = "vip"
_LOG_FORMAT = "%(levelname)s: %(message)s"


class Verbosity(enum.IntEnum):
    """How much :mod:`vip.output` prints; higher shows more."""

    QUIET = 0
    NORMAL = 1
    VERBOSE = 2


def parse_verbosity(value: str | None) -> Verbosity:
    """Map a ``quiet``/``normal``/``verbose`` string to a level; anything else is normal."""
    try:
        return Verbosity[(value or "").strip().upper()]
    except KeyError:
        return Verbosity.NORMAL


# Read at import so a subprocess (the pytest run behind ``vip verify``) inherits
# the parent's level through the environment.
_verbosity = parse_verbosity(os.environ.get(VERBOSITY_ENV_VAR))


class _StderrHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Stream handler that resolves ``sys.stderr`` per record, not at creation."""

    def __init__(self) -> None:
        """Create the handler without binding a stream."""
        logging.Handler.__init__(self)
        self.setFormatter(logging.Formatter(_LOG_FORMAT))

    @property
    def stream(self) -> TextIO:  # type: ignore[override]
        """Return the current ``sys.stderr``."""
        return sys.stderr

    @stream.setter
    def stream(self, _value: object) -> None:
        """Ignore assignment; the stream is always ``sys.stderr``."""


def get_verbosity() -> Verbosity:
    """Return the current verbosity level."""
    return _verbosity


def set_verbosity(level: Verbosity | str) -> None:
    """Set the verbosity level (a :class:`Verbosity` or its name) and retune logging."""
    global _verbosity
    _verbosity = parse_verbosity(level) if isinstance(level, str) else Verbosity(level)
    _sync_logger_level()


def _sync_logger_level() -> None:
    """Point an attached ``vip`` log handler's threshold at the current verbosity."""
    logger = logging.getLogger(_LOGGER_NAME)
    if any(isinstance(h, _StderrHandler) for h in logger.handlers):
        logger.setLevel(_log_level())


def _log_level() -> int:
    """Return the ``logging`` level that matches the current verbosity."""
    if _verbosity is Verbosity.VERBOSE:
        return logging.DEBUG
    if _verbosity is Verbosity.QUIET:
        return logging.WARNING
    return logging.INFO


def configure_logging() -> None:
    """Send ``vip.*`` log records to stderr at a level that follows the verbosity.

    Idempotent: attaches one handler to the ``vip`` logger however often it is called.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    if not any(isinstance(h, _StderrHandler) for h in logger.handlers):
        logger.addHandler(_StderrHandler())
        logger.propagate = False
    logger.setLevel(_log_level())


def _write(stream_name: str, msg: str, end: str) -> None:
    """Write *msg* to ``sys.<stream_name>`` (looked up now) and flush it."""
    stream = getattr(sys, stream_name)
    stream.write(f"{msg}{end}")
    stream.flush()


def out(msg: str = "", *, end: str = "\n") -> None:
    """Write a command result (data a caller may pipe) to stdout; always shown."""
    _write("stdout", msg, end)


def info(msg: str = "", *, end: str = "\n") -> None:
    """Write progress or status to stderr; hidden when quiet."""
    if _verbosity >= Verbosity.NORMAL:
        _write("stderr", msg, end)


def warn(msg: str = "", *, end: str = "\n") -> None:
    """Write a warning to stderr; shown at every level."""
    _write("stderr", msg, end)


def error(msg: str = "", *, end: str = "\n") -> None:
    """Write a failure to stderr; shown at every level."""
    _write("stderr", msg, end)


def debug(msg: str = "", *, end: str = "\n") -> None:
    """Write a diagnostic to stderr; shown only when verbose."""
    if _verbosity >= Verbosity.VERBOSE:
        _write("stderr", msg, end)
