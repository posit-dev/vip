"""Tests for the root ``-q/--quiet`` and ``-v/--verbose`` flags and their plumbing."""

from __future__ import annotations

import logging
import sys
from unittest.mock import patch

import pytest

from vip import output
from vip.cli import main
from vip.output import Verbosity


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["version"], Verbosity.NORMAL),
        (["-q", "version"], Verbosity.QUIET),
        (["--quiet", "version"], Verbosity.QUIET),
        (["-v", "version"], Verbosity.VERBOSE),
        (["--verbose", "version"], Verbosity.VERBOSE),
    ],
)
def test_root_flags_set_verbosity(monkeypatch, argv, expected):
    monkeypatch.delenv(output.VERBOSITY_ENV_VAR, raising=False)
    output.set_verbosity(Verbosity.NORMAL)
    monkeypatch.setattr(sys, "argv", ["vip", *argv])
    with patch("vip.cli.app.run_version"):
        main()
    assert output.get_verbosity() is expected


def test_quiet_and_verbose_are_mutually_exclusive(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["vip", "-q", "-v", "version"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_main_attaches_log_handler(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["vip", "version"])
    logger = logging.getLogger("vip")
    logger.handlers.clear()
    with patch("vip.cli.app.run_version"):
        main()
    assert any(isinstance(h, output._StderrHandler) for h in logger.handlers)


def test_verify_verbose_keeps_its_own_dest_and_enables_debug(monkeypatch, tmp_path):
    """``vip verify --verbose`` still means tracebacks, and now also debug output."""
    cfg = tmp_path / "vip.toml"
    cfg.write_text("[general]\n", encoding="utf-8")
    captured: dict = {}

    def fake_run_verify(args):
        captured["verbose"] = args.verbose
        captured["output_verbose"] = args.output_verbose

    monkeypatch.setattr(sys, "argv", ["vip", "verify", "--verbose", "--config", str(cfg)])
    with patch("vip.cli.app.run_verify", fake_run_verify):
        main()
    assert captured == {"verbose": True, "output_verbose": False}
    assert output.get_verbosity() is Verbosity.VERBOSE
