"""Tests for vip.output: stream choice, verbosity levels, env parsing, log bridge."""

from __future__ import annotations

import logging

import pytest

from vip import output
from vip.output import Verbosity


def test_out_goes_to_stdout_verbatim(capsys):
    output.out(">>> result")
    captured = capsys.readouterr()
    assert captured.out == ">>> result\n"
    assert captured.err == ""


def test_out_without_message_prints_blank_line(capsys):
    output.out()
    assert capsys.readouterr().out == "\n"


def test_end_is_honoured(capsys):
    output.out("a", end="")
    output.info("b", end="")
    captured = capsys.readouterr()
    assert captured.out == "a"
    assert captured.err == "b"


@pytest.mark.parametrize("fn", [output.info, output.warn, output.error, output.debug])
def test_diagnostic_functions_use_stderr(capsys, fn):
    output.set_verbosity(Verbosity.VERBOSE)
    fn("msg")
    captured = capsys.readouterr()
    assert captured.err == "msg\n"
    assert captured.out == ""


@pytest.mark.parametrize(
    ("level", "shown"),
    [
        (Verbosity.QUIET, {"out", "warn", "error"}),
        (Verbosity.NORMAL, {"out", "info", "warn", "error"}),
        (Verbosity.VERBOSE, {"out", "info", "warn", "error", "debug"}),
    ],
)
def test_levels(capsys, level, shown):
    output.set_verbosity(level)
    for name in ("out", "info", "warn", "error", "debug"):
        getattr(output, name)(name)
    captured = capsys.readouterr()
    assert set((captured.out + captured.err).split()) == shown


def test_set_verbosity_accepts_names():
    output.set_verbosity("verbose")
    assert output.get_verbosity() is Verbosity.VERBOSE


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("quiet", Verbosity.QUIET),
        ("QUIET", Verbosity.QUIET),
        (" verbose ", Verbosity.VERBOSE),
        ("normal", Verbosity.NORMAL),
        ("bogus", Verbosity.NORMAL),
        ("", Verbosity.NORMAL),
        (None, Verbosity.NORMAL),
    ],
)
def test_parse_verbosity(value, expected):
    assert output.parse_verbosity(value) is expected


def test_streams_resolved_at_call_time(capsys):
    # capsys swaps sys.stdout after import; a stream bound at import would miss it.
    output.out("late")
    assert capsys.readouterr().out == "late\n"


def _vip_handlers():
    return [h for h in logging.getLogger("vip").handlers if isinstance(h, output._StderrHandler)]


def test_configure_logging_is_idempotent():
    output.configure_logging()
    output.configure_logging()
    assert len(_vip_handlers()) == 1
    assert logging.getLogger("vip").propagate is False


def test_configure_logging_can_keep_propagation():
    output.configure_logging(propagate=True)
    assert len(_vip_handlers()) == 1
    assert logging.getLogger("vip").propagate is True


def test_pytest_subprocess_bridges_logging_at_env_level(pytester, monkeypatch):
    """The pytest run behind ``vip -v verify`` shows vip.* debug logs on stderr."""
    monkeypatch.setenv(output.VERBOSITY_ENV_VAR, "verbose")
    pytester.makepyfile(
        """
        import logging

        def test_logger_is_bridged():
            logger = logging.getLogger("vip")
            assert logger.level == logging.DEBUG
            assert logger.propagate is True
            assert any(type(h).__name__ == "_StderrHandler" for h in logger.handlers)
        """
    )
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    result.assert_outcomes(passed=1)


def test_logging_writes_to_stderr_with_format(capsys):
    output.configure_logging()
    logging.getLogger("vip.sub").info("hello")
    captured = capsys.readouterr()
    assert captured.err == "INFO: hello\n"
    assert captured.out == ""


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (Verbosity.QUIET, logging.WARNING),
        (Verbosity.NORMAL, logging.INFO),
        (Verbosity.VERBOSE, logging.DEBUG),
    ],
)
def test_logging_level_follows_verbosity(level, expected):
    output.set_verbosity(level)
    output.configure_logging()
    assert logging.getLogger("vip").level == expected


def test_set_verbosity_retunes_attached_logger():
    output.configure_logging()
    output.set_verbosity(Verbosity.VERBOSE)
    assert logging.getLogger("vip").level == logging.DEBUG


def test_quiet_hides_info_log_but_keeps_warning(capsys):
    output.set_verbosity(Verbosity.QUIET)
    output.configure_logging()
    log = logging.getLogger("vip.sub")
    log.info("hidden")
    log.warning("shown")
    assert capsys.readouterr().err == "WARNING: shown\n"
