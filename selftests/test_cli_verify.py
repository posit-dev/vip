"""Tests for _run_verify_local command assembly in vip.cli."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vip.cli import DEFAULT_TEST_TIMEOUT_SECONDS


def _make_args(**overrides) -> argparse.Namespace:
    """Build a minimal args namespace for _run_verify_local."""
    defaults = {
        "config": None,
        "connect_url": None,
        "workbench_url": None,
        "package_manager_url": None,
        "report": "report/results.json",
        "interactive_auth": False,
        "no_auth": False,
        "extensions": [],
        "categories": None,
        "filter_expr": None,
        "pytest_args": [],
        "verbose": False,
        "test_timeout": DEFAULT_TEST_TIMEOUT_SECONDS,
        "headless_auth": False,
        "idp": None,
        "performance_tests": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _capture_call(args: argparse.Namespace) -> tuple[list[str], dict]:
    """Run _run_verify_local with mocked subprocess and return (cmd, kwargs)."""
    captured: list[tuple[list[str], dict]] = []

    def fake_run(cmd, **kwargs):
        captured.append((list(cmd), kwargs))
        result = MagicMock()
        result.returncode = 0
        return result

    with (
        patch("vip.cli.subprocess.run", side_effect=fake_run),
        patch("vip.cli.sys.exit"),
    ):
        from vip.cli import _run_verify_local

        _run_verify_local(args)

    assert captured, "subprocess.run was never called"
    return captured[0]


def _capture_cmd(args: argparse.Namespace) -> list[str]:
    """Run _run_verify_local with mocked subprocess and return the command."""
    cmd, _kwargs = _capture_call(args)
    return cmd


def _vip_tests_path() -> str:
    """Return the resolved vip_tests package path for assertions."""
    from importlib.util import find_spec

    spec = find_spec("vip_tests")
    assert spec and spec.submodule_search_locations
    return spec.submodule_search_locations[0]


class TestVerifyLocalTestPath:
    """The CLI must pass the vip_tests package path to pytest so tests are
    found even when running outside the source tree (pip install)."""

    def test_vip_tests_path_included_by_default(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg)))
        assert _vip_tests_path() in cmd

    def test_vip_tests_path_skipped_when_user_passes_test_file(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), pytest_args=["tests/foo.py"]))
        assert _vip_tests_path() not in cmd

    def test_vip_tests_path_skipped_when_user_passes_nodeid(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), pytest_args=["tests/foo.py::test_bar"]))
        assert _vip_tests_path() not in cmd

    def test_vip_tests_path_kept_with_flag_only_pytest_args(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), pytest_args=["-x", "--tb=short"]))
        assert _vip_tests_path() in cmd

    def test_vip_tests_path_skipped_when_user_passes_directory_target(self, tmp_path):
        """A positional directory argument is a test target."""
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        target_dir = tmp_path / "my_tests"
        target_dir.mkdir()
        cmd = _capture_cmd(_make_args(config=str(cfg), pytest_args=[str(target_dir)]))
        assert _vip_tests_path() not in cmd

    def test_vip_tests_path_kept_when_dir_is_rootdir_value(self, tmp_path):
        """--rootdir value must not trigger false-positive target detection."""
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), pytest_args=["--rootdir", str(tmp_path)]))
        assert _vip_tests_path() in cmd

    def test_vip_tests_path_kept_when_dir_is_confcutdir_value(self, tmp_path):
        """--confcutdir value must not trigger false-positive target detection."""
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), pytest_args=["--confcutdir", str(tmp_path)]))
        assert _vip_tests_path() in cmd


class TestVerifyLocalSkipNotes:
    """Unconfigured products should produce a note before tests run."""

    def test_disabled_product_says_disabled(self, tmp_path, capsys):
        cfg = tmp_path / "vip.toml"
        cfg.write_text(
            "[general]\n"
            "[connect]\nenabled = false\n"
            "[workbench]\nenabled = false\n"
            '[package_manager]\nurl = "http://localhost:4242/"\n'
        )
        _capture_cmd(_make_args(config=str(cfg)))
        out = capsys.readouterr().out
        assert "Connect disabled" in out
        assert "Workbench disabled" in out
        assert "Package Manager" not in out

    def test_missing_url_says_no_url(self, tmp_path, capsys):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        _capture_cmd(_make_args(config=str(cfg)))
        out = capsys.readouterr().out
        assert "Connect no URL given" in out
        assert "Workbench no URL given" in out
        assert "Package Manager no URL given" in out

    def test_no_notes_when_all_products_configured(self, tmp_path, capsys):
        cfg = tmp_path / "vip.toml"
        cfg.write_text(
            "[general]\n"
            '[connect]\nurl = "https://c.example.com"\n'
            '[workbench]\nurl = "https://w.example.com"\n'
            '[package_manager]\nurl = "https://pm.example.com"\n'
        )
        _capture_cmd(_make_args(config=str(cfg)))
        out = capsys.readouterr().out
        assert "will not be collected" not in out

    def test_notes_from_url_args(self, tmp_path, monkeypatch, capsys):
        """URL-argument flow generates a temp config; notes should reflect it."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        _capture_cmd(_make_args(package_manager_url="http://localhost:4242/"))
        out = capsys.readouterr().out
        assert "Connect disabled" in out
        assert "will not be collected" in out
        assert "Workbench disabled" in out
        assert "Package Manager" not in out


class TestVerifyLocalCredentialCheck:
    """Exit early when products are configured but credentials are missing."""

    def _run_and_expect_exit(self, args):
        from vip.cli import _run_verify_local

        with pytest.raises(SystemExit) as exc_info:
            _run_verify_local(args)
        assert exc_info.value.code == 1

    def test_workbench_url_without_creds_exits(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        monkeypatch.delenv("VIP_TEST_USERNAME", raising=False)
        monkeypatch.delenv("VIP_TEST_PASSWORD", raising=False)
        self._run_and_expect_exit(_make_args(workbench_url="https://wb.example.com"))
        err = capsys.readouterr().err
        assert "Workbench" in err
        assert "VIP_TEST_USERNAME" in err

    def test_connect_url_without_creds_exits(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        monkeypatch.delenv("VIP_TEST_USERNAME", raising=False)
        monkeypatch.delenv("VIP_TEST_PASSWORD", raising=False)
        monkeypatch.delenv("VIP_CONNECT_API_KEY", raising=False)
        self._run_and_expect_exit(_make_args(connect_url="https://c.example.com"))
        err = capsys.readouterr().err
        assert "Connect" in err

    def test_both_urls_without_creds_exits(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        monkeypatch.delenv("VIP_TEST_USERNAME", raising=False)
        monkeypatch.delenv("VIP_TEST_PASSWORD", raising=False)
        monkeypatch.delenv("VIP_CONNECT_API_KEY", raising=False)
        self._run_and_expect_exit(
            _make_args(
                connect_url="https://c.example.com",
                workbench_url="https://wb.example.com",
            )
        )
        err = capsys.readouterr().err
        assert "Connect and Workbench" in err

    def test_username_only_still_exits(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        monkeypatch.setenv("VIP_TEST_USERNAME", "admin")
        monkeypatch.delenv("VIP_TEST_PASSWORD", raising=False)
        self._run_and_expect_exit(_make_args(workbench_url="https://wb.example.com"))

    def test_password_only_still_exits(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        monkeypatch.delenv("VIP_TEST_USERNAME", raising=False)
        monkeypatch.setenv("VIP_TEST_PASSWORD", "secret")
        self._run_and_expect_exit(_make_args(workbench_url="https://wb.example.com"))

    def test_connect_with_api_key_still_exits(self, tmp_path, monkeypatch):
        """Connect UI/user-management scenarios need username/password even with an API key."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        monkeypatch.delenv("VIP_TEST_USERNAME", raising=False)
        monkeypatch.delenv("VIP_TEST_PASSWORD", raising=False)
        monkeypatch.setenv("VIP_CONNECT_API_KEY", "abc123")
        self._run_and_expect_exit(_make_args(connect_url="https://c.example.com"))

    def test_with_both_creds_no_exit(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        monkeypatch.setenv("VIP_TEST_USERNAME", "admin")
        monkeypatch.setenv("VIP_TEST_PASSWORD", "secret")
        _capture_cmd(_make_args(workbench_url="https://wb.example.com"))

    def test_interactive_auth_no_exit(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        monkeypatch.delenv("VIP_TEST_USERNAME", raising=False)
        monkeypatch.delenv("VIP_TEST_PASSWORD", raising=False)
        _capture_cmd(_make_args(workbench_url="https://wb.example.com", interactive_auth=True))

    def test_package_manager_only_no_exit(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        monkeypatch.delenv("VIP_TEST_USERNAME", raising=False)
        monkeypatch.delenv("VIP_TEST_PASSWORD", raising=False)
        _capture_cmd(_make_args(package_manager_url="https://pm.example.com"))

    def test_category_filter_skips_unselected_product(self, tmp_path, monkeypatch):
        """Workbench configured but only package-manager category selected."""
        cfg = tmp_path / "vip.toml"
        cfg.write_text(
            "[general]\n"
            '[workbench]\nurl = "https://wb.example.com"\n'
            '[package_manager]\nurl = "https://pm.example.com"\n'
        )
        monkeypatch.delenv("VIP_TEST_USERNAME", raising=False)
        monkeypatch.delenv("VIP_TEST_PASSWORD", raising=False)
        _capture_cmd(_make_args(config=str(cfg), categories="package_manager"))

    def test_category_filter_still_exits_for_selected_product(self, tmp_path, monkeypatch):
        """Workbench category selected without credentials should still exit."""
        cfg = tmp_path / "vip.toml"
        cfg.write_text(
            "[general]\n"
            '[workbench]\nurl = "https://wb.example.com"\n'
            '[package_manager]\nurl = "https://pm.example.com"\n'
        )
        monkeypatch.delenv("VIP_TEST_USERNAME", raising=False)
        monkeypatch.delenv("VIP_TEST_PASSWORD", raising=False)
        self._run_and_expect_exit(_make_args(config=str(cfg), categories="workbench"))

    def test_negated_category_skips_credential_check(self, tmp_path, monkeypatch):
        """'not workbench' should NOT require workbench credentials."""
        cfg = tmp_path / "vip.toml"
        cfg.write_text(
            "[general]\n"
            '[workbench]\nurl = "https://wb.example.com"\n'
            '[package_manager]\nurl = "https://pm.example.com"\n'
        )
        monkeypatch.delenv("VIP_TEST_USERNAME", raising=False)
        monkeypatch.delenv("VIP_TEST_PASSWORD", raising=False)
        _capture_cmd(_make_args(config=str(cfg), categories="not workbench"))

    def test_no_auth_bypasses_credential_check(self, tmp_path, monkeypatch):
        """--no-auth should not exit even without credentials."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        monkeypatch.delenv("VIP_TEST_USERNAME", raising=False)
        monkeypatch.delenv("VIP_TEST_PASSWORD", raising=False)
        _capture_cmd(_make_args(workbench_url="https://wb.example.com", no_auth=True))

    def test_no_auth_passes_flag_to_pytest(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        cmd = _capture_cmd(_make_args(workbench_url="https://wb.example.com", no_auth=True))
        assert "--no-auth" in cmd

    def test_error_message_mentions_no_auth(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        monkeypatch.delenv("VIP_TEST_USERNAME", raising=False)
        monkeypatch.delenv("VIP_TEST_PASSWORD", raising=False)
        self._run_and_expect_exit(_make_args(workbench_url="https://wb.example.com"))
        err = capsys.readouterr().err
        assert "--no-auth" in err


class TestVerifyLocalVerbose:
    """Review #87: verify -v is included by default in local runs."""

    def test_verbose_flag_present_by_default(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg)))
        assert "-v" in cmd

    def test_user_pytest_args_appended_after_verbose(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), pytest_args=["-x", "--tb=short"]))
        assert "-v" in cmd
        assert "-x" in cmd
        assert "--tb=short" in cmd


class TestVerifyLocalMissingConfig:
    """Review #88: verify exits immediately when config file is missing."""

    def test_explicit_config_missing_exits(self, tmp_path):
        missing = str(tmp_path / "does_not_exist.toml")
        with pytest.raises(SystemExit) as exc_info:
            from vip.cli import _run_verify_local

            _run_verify_local(_make_args(config=missing))
        assert exc_info.value.code == 1

    def test_no_config_no_urls_missing_default_exits(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            from vip.cli import _run_verify_local

            _run_verify_local(_make_args())
        assert exc_info.value.code == 1

    def test_url_args_bypass_missing_default(self, tmp_path, monkeypatch):
        """When URL args are provided, a temp config is generated — no default needed."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        cmd = _capture_cmd(_make_args(connect_url="https://connect.example.com"))
        assert any("--vip-config" in arg for arg in cmd)


class TestVerifyLocalConfigPath:
    """Regression: the resolved config path must be passed to pytest as an
    absolute path so downstream CWD/rootdir changes cannot cause pytest to
    load a different (or missing) vip.toml (issue #170)."""

    def test_default_vip_toml_passed_as_absolute_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        cfg = tmp_path / "vip.toml"
        cfg.write_text(
            '[general]\ndeployment_name = "x"\n'
            '[connect]\nurl = "https://myserver.example.com/pct"\n'
        )
        cmd = _capture_cmd(_make_args())
        cfg_args = [c for c in cmd if c.startswith("--vip-config=")]
        assert cfg_args, "pytest command must include --vip-config"
        cfg_path = cfg_args[0].split("=", 1)[1]
        assert Path(cfg_path).is_absolute()
        assert Path(cfg_path).resolve() == cfg.resolve()

    def test_explicit_config_passed_as_absolute_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = tmp_path / "custom.toml"
        cfg.write_text('[general]\ndeployment_name = "x"\n')
        cmd = _capture_cmd(_make_args(config="custom.toml"))
        cfg_args = [c for c in cmd if c.startswith("--vip-config=")]
        assert cfg_args
        assert Path(cfg_args[0].split("=", 1)[1]).is_absolute()


class TestVerifyLocalVerboseFlag:
    """vip verify --verbose should pass --vip-verbose to pytest."""

    def test_verbose_flag_passes_vip_verbose(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), verbose=True))
        assert "--vip-verbose" in cmd

    def test_verbose_flag_disables_capture(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), verbose=True))
        assert "-s" in cmd

    def test_no_verbose_does_not_disable_capture(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), verbose=False))
        assert "-s" not in cmd

    def test_no_verbose_flag_omits_vip_verbose(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), verbose=False))
        assert "--vip-verbose" not in cmd


class TestNormalizeCategories:
    """_normalize_categories should accept hyphenated names and reject invalid ones."""

    def test_hyphenated_category_normalized_to_underscore(self):
        from vip.cli import _normalize_categories

        assert _normalize_categories("package-manager") == "package_manager"

    def test_plain_category_passes_through(self):
        from vip.cli import _normalize_categories

        assert _normalize_categories("connect") == "connect"

    def test_compound_expression_normalized(self):
        from vip.cli import _normalize_categories

        assert _normalize_categories("package-manager and cross-product") == (
            "package_manager and cross_product"
        )

    def test_invalid_category_exits(self):
        from vip.cli import _normalize_categories

        with pytest.raises(SystemExit) as exc_info:
            _normalize_categories("bogus")
        assert exc_info.value.code == 1

    def test_invalid_category_in_expression_exits(self):
        from vip.cli import _normalize_categories

        with pytest.raises(SystemExit) as exc_info:
            _normalize_categories("connect and bogus")
        assert exc_info.value.code == 1

    def test_not_expression_accepted(self):
        from vip.cli import _normalize_categories

        assert _normalize_categories("not performance") == "not performance"

    def test_or_expression_accepted(self):
        from vip.cli import _normalize_categories

        assert _normalize_categories("connect or workbench") == "connect or workbench"

    def test_all_hyphenated_categories_accepted(self):
        from vip.cli import _normalize_categories

        assert _normalize_categories("package-manager") == "package_manager"
        assert _normalize_categories("cross-product") == "cross_product"

    def test_underscore_category_accepted_for_backward_compat(self):
        from vip.cli import _normalize_categories

        assert _normalize_categories("package_manager") == "package_manager"
        assert _normalize_categories("cross_product") == "cross_product"

    def test_nested_parentheses(self):
        from vip.cli import _normalize_categories

        result = _normalize_categories("(connect and (workbench or performance))")
        assert result == "(connect and (workbench or performance))"

    def test_parenthesized_expression(self):
        from vip.cli import _normalize_categories

        result = _normalize_categories("(package-manager or cross-product)")
        assert result == "(package_manager or cross_product)"

    def test_leading_underscore_rejected(self):
        from vip.cli import _normalize_categories

        with pytest.raises(SystemExit) as exc_info:
            _normalize_categories("_connect")
        assert exc_info.value.code == 1

    def test_leading_digit_rejected(self):
        from vip.cli import _normalize_categories

        with pytest.raises(SystemExit) as exc_info:
            _normalize_categories("1connect")
        assert exc_info.value.code == 1

    def test_config_hygiene_category_accepted(self):
        from vip.cli import _normalize_categories

        assert _normalize_categories("config-hygiene") == "config_hygiene"
        assert _normalize_categories("config_hygiene") == "config_hygiene"


class TestConfigHygieneOptIn:
    """config_hygiene tests are excluded from the default vip verify run."""

    @staticmethod
    def _marker_expr(cmd: list[str]) -> str:
        """Return the pytest marker expression, skipping ``python -m pytest``."""
        # cmd looks like [python, "-m", "pytest", ..., "-m", "<expr>", ...]
        # The first "-m" introduces the pytest module; the second is the
        # marker filter we want to inspect.
        first = cmd.index("-m")
        second = cmd.index("-m", first + 1)
        return cmd[second + 1]

    def test_default_filter_excludes_config_hygiene(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg)))
        assert "not config_hygiene" in self._marker_expr(cmd)

    def test_explicit_category_overrides_default_filter(self, tmp_path):
        """When the user passes --categories, the default exclusion is replaced."""
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), categories="package-manager"))
        # Exactly two "-m" tokens: ``python -m pytest`` and ``-m <expr>``.
        assert cmd.count("-m") == 2
        assert self._marker_expr(cmd) == "package_manager"

    def test_opt_in_runs_config_hygiene_tests(self, tmp_path):
        """Passing --categories config-hygiene runs exactly that category."""
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), categories="config-hygiene"))
        assert self._marker_expr(cmd) == "config_hygiene"

    def test_default_marker_expr_names_every_opt_in_category(self):
        """_default_marker_expr excludes each category in _OPT_IN_CATEGORIES."""
        from vip.cli import _OPT_IN_CATEGORIES, _default_marker_expr

        expr = _default_marker_expr()
        for category in _OPT_IN_CATEGORIES:
            assert f"not {category}" in expr


class TestPerformanceOptIn:
    """performance tests are excluded by default and run with --performance-tests."""

    @staticmethod
    def _marker_expr(cmd: list[str]) -> str:
        """Return the pytest marker expression from the assembled command."""
        first = cmd.index("-m")
        second = cmd.index("-m", first + 1)
        return cmd[second + 1]

    def test_default_filter_excludes_performance(self, tmp_path):
        """Without --performance-tests, the marker expression excludes performance."""
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg)))
        assert "not performance" in self._marker_expr(cmd)

    def test_performance_tests_flag_removes_exclusion(self, tmp_path):
        """With --performance-tests, performance is no longer excluded from the expr."""
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), performance_tests=True))
        assert "not performance" not in self._marker_expr(cmd)

    def test_explicit_category_overrides_performance_flag(self, tmp_path):
        """When --categories is set, --performance-tests has no effect on the expr."""
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(
            _make_args(config=str(cfg), categories="connect", performance_tests=True)
        )
        assert self._marker_expr(cmd) == "connect"

    @staticmethod
    def _capture_k8s_categories(args: argparse.Namespace) -> str:
        """Run _run_k8s_job with mocked K8s helpers and return the categories= value."""
        from unittest.mock import MagicMock, patch

        captured: dict[str, str] = {}

        def fake_create_job(_job_name, _namespace, _cm_name, **kwargs):
            captured["categories"] = kwargs.get("categories", "")

        with (
            patch("vip.cli.secrets.token_hex", return_value="abcd1234"),
            patch("vip.verify.job.create_config_map"),
            patch("vip.verify.job.create_job", side_effect=fake_create_job),
            patch("vip.verify.job.stream_logs"),
            patch(
                "vip.verify.job.wait_for_job",
                return_value=MagicMock(status=MagicMock(failed=None)),
            ),
            patch("vip.verify.job.cleanup"),
        ):
            from vip.cli import _run_k8s_job

            _run_k8s_job("[general]\n", args)
        return captured.get("categories", "")

    def test_k8s_default_excludes_performance(self):
        """K8s path: without --performance-tests, categories expr excludes performance."""
        args = argparse.Namespace(
            categories=None,
            performance_tests=False,
            namespace="posit-team",
            image="vip:latest",
            timeout=3600,
            filter_expr=None,
            verbose=False,
        )
        categories = self._capture_k8s_categories(args)
        assert "not performance" in categories

    def test_k8s_flag_removes_exclusion(self):
        """K8s path: with --performance-tests, performance is not excluded."""
        args = argparse.Namespace(
            categories=None,
            performance_tests=True,
            namespace="posit-team",
            image="vip:latest",
            timeout=3600,
            filter_expr=None,
            verbose=False,
        )
        categories = self._capture_k8s_categories(args)
        assert "not performance" not in categories


class TestExtraKeepFromArgs:
    """_extra_keep_from_args mirrors --performance-tests on both local and K8s paths."""

    def test_no_flag_returns_empty(self):
        """Without --performance-tests the extra-keep set is empty."""
        from vip.cli import _default_marker_expr, _extra_keep_from_args

        args = argparse.Namespace(performance_tests=False)
        extra = _extra_keep_from_args(args)
        assert extra == frozenset()
        assert "not performance" in _default_marker_expr(extra)

    def test_flag_includes_performance(self):
        """With --performance-tests the extra-keep set contains 'performance'."""
        from vip.cli import _default_marker_expr, _extra_keep_from_args

        args = argparse.Namespace(performance_tests=True)
        extra = _extra_keep_from_args(args)
        assert "performance" in extra
        assert "not performance" not in _default_marker_expr(extra)

    def test_missing_attr_treated_as_false(self):
        """If performance_tests attribute is absent (K8s path before flag), treat as False."""
        from vip.cli import _extra_keep_from_args

        args = argparse.Namespace()  # no performance_tests attr
        assert _extra_keep_from_args(args) == frozenset()


class TestVerifyLocalTestTimeout:
    """--test-timeout should limit how long the subprocess can run."""

    def test_argparse_default_matches_constant(self, tmp_path, monkeypatch):
        """The real CLI parser must resolve ``--test-timeout`` to the shared
        ``DEFAULT_TEST_TIMEOUT_SECONDS`` constant.

        Guards against regressing the argparse default in isolation from the
        constant (or vice versa) — the two must stay in lockstep.
        """
        import sys

        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")

        captured: dict[str, int] = {}

        def fake_run_verify(args):
            captured["test_timeout"] = args.test_timeout
            raise SystemExit(0)

        monkeypatch.setattr("vip.cli.run_verify", fake_run_verify)
        monkeypatch.setattr(sys, "argv", ["vip", "verify", "--config", str(cfg)])

        from vip.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        assert captured["test_timeout"] == DEFAULT_TEST_TIMEOUT_SECONDS
        # Guard against a surprise change to the expected default itself.
        assert DEFAULT_TEST_TIMEOUT_SECONDS == 3600

    def test_default_timeout_passed_to_subprocess(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        _cmd, kwargs = _capture_call(_make_args(config=str(cfg)))
        assert kwargs["timeout"] == DEFAULT_TEST_TIMEOUT_SECONDS

    def test_custom_timeout_passed_through(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        _cmd, kwargs = _capture_call(_make_args(config=str(cfg), test_timeout=600))
        assert kwargs["timeout"] == 600

    def test_timeout_expired_exits_with_error(self, tmp_path, capsys):
        import subprocess as real_subprocess

        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")

        def fake_run(cmd, **kwargs):
            raise real_subprocess.TimeoutExpired(
                cmd, kwargs.get("timeout", DEFAULT_TEST_TIMEOUT_SECONDS)
            )

        with (
            patch("vip.cli.subprocess.run", side_effect=fake_run),
            pytest.raises(SystemExit) as exc_info,
        ):
            from vip.cli import _run_verify_local

            _run_verify_local(_make_args(config=str(cfg)))

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "timed out" in err.lower()


class TestHeadlessAuth:
    def test_headless_auth_flag_passed_to_pytest(self, tmp_path):
        cfg = tmp_path / "vip.toml"
        cfg.write_text("[general]\n")
        cmd = _capture_cmd(_make_args(config=str(cfg), headless_auth=True))
        assert "--headless-auth" in cmd

    def test_headless_auth_skips_credential_check(self, tmp_path, capsys, monkeypatch):
        """--headless-auth should skip the credential check like --interactive-auth."""
        monkeypatch.delenv("VIP_TEST_USERNAME", raising=False)
        monkeypatch.delenv("VIP_TEST_PASSWORD", raising=False)
        monkeypatch.delenv("VIP_CONNECT_API_KEY", raising=False)
        cfg = tmp_path / "vip.toml"
        cfg.write_text('[general]\n[connect]\nurl = "https://c.example.com"\n')
        # Without headless_auth, missing credentials produce an error message.
        _capture_cmd(_make_args(config=str(cfg)))
        err = capsys.readouterr().err
        assert "no credentials provided" in err
        # With headless_auth, credential check is bypassed — no error.
        _capture_cmd(_make_args(config=str(cfg), headless_auth=True))
        err = capsys.readouterr().err
        assert "no credentials provided" not in err


class TestAuthCliFlags:
    """--idp is written to the generated temp config and implies provider."""

    def test_idp_implies_oidc_provider(self, tmp_path, monkeypatch):
        """--idp alone infers provider = 'oidc' in the temp config."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        from vip.cli import _generate_temp_config
        from vip.config import load_config

        path = _generate_temp_config(_make_args(workbench_url="https://wb.example.com", idp="okta"))
        try:
            cfg = load_config(path)
            assert cfg.auth.idp == "okta"
            assert cfg.auth.provider == "oidc"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_no_auth_section_when_idp_omitted(self, tmp_path, monkeypatch):
        """Without --idp or an existing vip.toml, auth defaults are used."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        from vip.cli import _generate_temp_config
        from vip.config import load_config

        path = _generate_temp_config(_make_args(connect_url="https://c.example.com"))
        try:
            cfg = load_config(path)
            assert cfg.auth.provider == "password"  # default
            assert cfg.auth.idp == ""  # default
        finally:
            Path(path).unlink(missing_ok=True)

    def test_auth_inherited_from_existing_vip_toml(self, tmp_path, monkeypatch):
        """With no --idp flag, inherit provider and idp from existing vip.toml."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        (tmp_path / "vip.toml").write_text('[general]\n[auth]\nprovider = "saml"\nidp = "okta"\n')
        from vip.cli import _generate_temp_config
        from vip.config import load_config

        path = _generate_temp_config(_make_args(workbench_url="https://wb.example.com"))
        try:
            cfg = load_config(path)
            assert cfg.auth.provider == "saml"
            assert cfg.auth.idp == "okta"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_cli_idp_overrides_existing_vip_toml(self, tmp_path, monkeypatch):
        """Explicit --idp takes precedence over vip.toml's idp."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        (tmp_path / "vip.toml").write_text('[general]\n[auth]\nprovider = "saml"\nidp = "okta"\n')
        from vip.cli import _generate_temp_config
        from vip.config import load_config

        path = _generate_temp_config(
            _make_args(workbench_url="https://wb.example.com", idp="keycloak")
        )
        try:
            cfg = load_config(path)
            assert cfg.auth.idp == "keycloak"  # CLI override
            assert cfg.auth.provider == "saml"  # provider preserved from vip.toml
        finally:
            Path(path).unlink(missing_ok=True)

    def test_non_oidc_provider_preserved_from_vip_toml(self, tmp_path, monkeypatch):
        """A non-default provider (ldap) in vip.toml is inherited even without idp."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        (tmp_path / "vip.toml").write_text('[general]\n[auth]\nprovider = "ldap"\n')
        from vip.cli import _generate_temp_config
        from vip.config import load_config

        path = _generate_temp_config(_make_args(workbench_url="https://wb.example.com"))
        try:
            cfg = load_config(path)
            assert cfg.auth.provider == "ldap"
            assert cfg.auth.idp == ""
        finally:
            Path(path).unlink(missing_ok=True)

    def test_cli_idp_overrides_conflicting_non_idp_provider(self, tmp_path, monkeypatch):
        """--idp must win over a non-IdP inherited provider (e.g. ldap).

        Without this, auth.py's flow selection would key off provider=ldap and
        fill the native login form, ignoring the requested IdP strategy.
        """
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        (tmp_path / "vip.toml").write_text('[general]\n[auth]\nprovider = "ldap"\n')
        from vip.cli import _generate_temp_config
        from vip.config import load_config

        path = _generate_temp_config(
            _make_args(workbench_url="https://wb.example.com", idp="keycloak")
        )
        try:
            cfg = load_config(path)
            assert cfg.auth.provider == "oidc"  # ldap dropped because it conflicts
            assert cfg.auth.idp == "keycloak"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_cli_idp_preserves_inherited_idp_class_provider(self, tmp_path, monkeypatch):
        """--idp should keep an inherited IdP-class provider (saml/oauth2)."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        (tmp_path / "vip.toml").write_text('[general]\n[auth]\nprovider = "oauth2"\n')
        from vip.cli import _generate_temp_config
        from vip.config import load_config

        path = _generate_temp_config(
            _make_args(workbench_url="https://wb.example.com", idp="keycloak")
        )
        try:
            cfg = load_config(path)
            assert cfg.auth.provider == "oauth2"  # IdP-class — preserved
            assert cfg.auth.idp == "keycloak"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_malformed_vip_toml_does_not_break_url_driven_path(self, tmp_path, monkeypatch):
        """A malformed local vip.toml should not crash a URL-driven CLI invocation."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("VIP_CONFIG", raising=False)
        (tmp_path / "vip.toml").write_text("this is = not valid toml [[[")
        from vip.cli import _generate_temp_config
        from vip.config import load_config

        path = _generate_temp_config(
            _make_args(workbench_url="https://wb.example.com", idp="keycloak")
        )
        try:
            cfg = load_config(path)
            assert cfg.auth.idp == "keycloak"
            assert cfg.auth.provider == "oidc"
        finally:
            Path(path).unlink(missing_ok=True)
