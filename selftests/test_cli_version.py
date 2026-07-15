"""Tests for ``vip --version`` and the ``vip version`` subcommand."""

from __future__ import annotations

import sys

import pytest


class TestMinimumSupportedVersion:
    """The declared MINIMUM_SUPPORTED_POSIT_TEAM support floor."""

    def test_parses_as_posit_calendar_version(self):
        from vip.version import MINIMUM_SUPPORTED_POSIT_TEAM, ProductVersion

        # Raises ValueError if the declared floor is malformed.
        ProductVersion(MINIMUM_SUPPORTED_POSIT_TEAM)

    def test_value_is_pinned(self):
        # Guard against an accidental edit: the support floor is a deliberate
        # policy decision, so changing it must be intentional.
        from vip.version import MINIMUM_SUPPORTED_POSIT_TEAM

        assert MINIMUM_SUPPORTED_POSIT_TEAM == "2026.04.0"


class TestVersionFlag:
    """``vip --version`` prints the vip version (one line) and exits 0."""

    def test_prints_version_and_exits(self, capsys, monkeypatch):
        from vip import __version__
        from vip.cli import main

        monkeypatch.setattr(sys, "argv", ["vip", "--version"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert out.strip() == f"vip {__version__}"

    def test_does_not_print_support_floor(self, capsys, monkeypatch):
        from vip.cli import main

        monkeypatch.setattr(sys, "argv", ["vip", "--version"])
        with pytest.raises(SystemExit):
            main()
        out = capsys.readouterr().out
        assert "supported" not in out.lower()


class TestVersionSubcommand:
    """``vip version`` prints the vip version and the support floor."""

    def test_prints_version_and_floor(self, capsys, monkeypatch):
        from vip import __version__
        from vip.cli import main
        from vip.version import MINIMUM_SUPPORTED_POSIT_TEAM

        monkeypatch.setattr(sys, "argv", ["vip", "version"])
        main()  # a subcommand returns normally; no SystemExit
        out = capsys.readouterr().out
        assert f"vip {__version__}" in out
        assert MINIMUM_SUPPORTED_POSIT_TEAM in out
        assert "minimum supported posit team version" in out.lower()
