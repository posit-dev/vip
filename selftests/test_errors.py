"""Tests for the VipError hierarchy and cli.main's exit handler."""

from __future__ import annotations

import sys

import pytest

import vip.auth
import vip.cli
import vip.cli.app
from vip.errors import (
    AuthConfigError,
    AuthError,
    AuthTimeoutError,
    ConfigError,
    InstallError,
    ProductUnreachableError,
    ReportError,
    VipError,
)


class TestVipErrorExitCodes:
    def test_default_exit_code_is_one(self):
        assert VipError("boom").exit_code == 1

    def test_exit_code_is_overridable(self):
        assert VipError("boom", exit_code=3).exit_code == 3

    def test_message_is_the_str_representation(self):
        assert str(VipError("boom")) == "boom"

    @pytest.mark.parametrize(
        "cls",
        [ConfigError, AuthError, ProductUnreachableError, InstallError, ReportError],
    )
    def test_subclasses_are_vip_errors(self, cls):
        assert issubclass(cls, VipError)
        assert cls("boom").exit_code == 1


class TestAuthConfigErrorReparenting:
    """AuthConfigError moved into errors.py and is re-parented onto AuthError,
    not replaced -- existing raise/except/selftest sites must keep working
    unchanged. See the errors-hierarchy PR body and issue #263.
    """

    def test_auth_config_error_is_an_auth_error(self):
        assert issubclass(AuthConfigError, AuthError)

    def test_auth_timeout_error_is_an_auth_config_error(self):
        assert issubclass(AuthTimeoutError, AuthConfigError)
        with pytest.raises(AuthConfigError) as excinfo:
            raise AuthTimeoutError("boom")
        assert isinstance(excinfo.value, AuthTimeoutError)

    def test_vip_auth_reexports_the_same_classes(self):
        assert vip.auth.AuthConfigError is AuthConfigError
        assert vip.auth.AuthTimeoutError is AuthTimeoutError


class TestCliSingleExitHandler:
    """cli.main's args.func(args) dispatch is the one place that catches
    VipError and turns it into a printed message plus sys.exit(exit_code).
    """

    def test_vip_error_exits_with_its_exit_code(self, monkeypatch, capsys):
        def _boom(_args):
            raise ConfigError("bad config", exit_code=3)

        monkeypatch.setattr(vip.cli.app, "run_version", _boom)
        monkeypatch.setattr(sys, "argv", ["vip", "version"])

        with pytest.raises(SystemExit) as exc_info:
            vip.cli.main()

        assert exc_info.value.code == 3
        assert capsys.readouterr().err == "Error: bad config\n"

    def test_vip_error_default_exit_code_is_one(self, monkeypatch, capsys):
        def _boom(_args):
            raise ReportError("quarto not found")

        monkeypatch.setattr(vip.cli.app, "run_version", _boom)
        monkeypatch.setattr(sys, "argv", ["vip", "version"])

        with pytest.raises(SystemExit) as exc_info:
            vip.cli.main()

        assert exc_info.value.code == 1
        assert capsys.readouterr().err == "Error: quarto not found\n"

    def test_non_vip_error_is_not_caught_by_the_handler(self, monkeypatch):
        def _boom(_args):
            raise RuntimeError("unexpected")

        monkeypatch.setattr(vip.cli.app, "run_version", _boom)
        monkeypatch.setattr(sys, "argv", ["vip", "version"])

        with pytest.raises(RuntimeError, match="unexpected"):
            vip.cli.main()
