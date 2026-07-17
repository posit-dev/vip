"""Tests for the ``vip report`` subcommand (run_report in vip.cli).

These cover the fix that lets ``vip report`` render from any working
directory (not just a source checkout): the Quarto templates are bundled in
the wheel and copied into the working ``report/`` dir, and the command fails
loudly instead of silently producing nothing.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest


def _make_args(**overrides) -> argparse.Namespace:
    defaults = {"results": "report/results.json", "open": False}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _fake_quarto(create_output: bool):
    """Return a subprocess.run stand-in that fakes a quarto render.

    When ``create_output`` is true it writes the index.html that a real
    render would produce, so run_report's success path can be exercised
    without Quarto installed.
    """

    def _run(cmd, cwd=None, **kwargs):
        if create_output and cwd is not None:
            from pathlib import Path

            out = Path(cwd) / "_output"
            out.mkdir(parents=True, exist_ok=True)
            (out / "index.html").write_text("<html>report</html>")
        return types.SimpleNamespace(returncode=0)

    return _run


def _fake_bundled_templates(monkeypatch, tmp_path) -> Path:
    """Point importlib.resources at a fake installed ``vip/_report`` directory.

    Selftests run from an editable install where the wheel bundle does not
    exist, so tests of the bundled-refresh path fake one on disk.
    """
    import importlib.resources

    from vip.cli import _REPORT_TEMPLATE_FILES

    pkg_root = tmp_path / "installed-vip"
    bundled = pkg_root / "_report"
    bundled.mkdir(parents=True)
    for name in _REPORT_TEMPLATE_FILES:
        (bundled / name).write_text(f"packaged {name}\n")
    monkeypatch.setattr(importlib.resources, "files", lambda pkg: pkg_root)
    return bundled


class TestEnsureReportTemplates:
    """_ensure_report_templates populates a working directory from a checkout/wheel."""

    def test_copies_template_files_into_empty_dir(self, tmp_path):
        from vip.cli import _REPORT_TEMPLATE_FILES, _ensure_report_templates

        report_dir = tmp_path / "report"
        report_dir.mkdir()

        assert _ensure_report_templates(report_dir) is True
        for name in _REPORT_TEMPLATE_FILES:
            assert (report_dir / name).is_file(), f"missing {name}"

    def test_styles_css_has_badge_rules(self, tmp_path):
        from vip.cli import _ensure_report_templates

        report_dir = tmp_path / "report"
        report_dir.mkdir()
        _ensure_report_templates(report_dir)

        assert ".badge-connect" in (report_dir / "styles.css").read_text()

    def test_partial_template_set_is_not_complete(self, tmp_path):
        from vip.cli import _REPORT_TEMPLATE_FILES, _has_all_report_templates

        report_dir = tmp_path / "report"
        report_dir.mkdir()
        # Only one of the required files present — must not count as complete.
        (report_dir / "index.qmd").write_text("x")
        assert _has_all_report_templates(report_dir) is False

        for name in _REPORT_TEMPLATE_FILES:
            (report_dir / name).write_text("x")
        assert _has_all_report_templates(report_dir) is True

    def test_pyproject_force_include_matches_template_list(self):
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib

        from vip.cli import _REPORT_TEMPLATE_FILES

        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        with pyproject.open("rb") as f:
            data = tomllib.load(f)
        force_include = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]

        expected = {f"report/{name}": f"vip/_report/{name}" for name in _REPORT_TEMPLATE_FILES}
        bundled = {s: d for s, d in force_include.items() if d.startswith("vip/_report/")}
        assert bundled == expected


class TestTemplateRefresh:
    """The bundled-template refresh is loud about overwrites and skips identical files."""

    def test_customized_template_is_refreshed_with_notice(self, tmp_path, monkeypatch, capsys):
        from vip.cli import _ensure_report_templates

        _fake_bundled_templates(monkeypatch, tmp_path)
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        _ensure_report_templates(report_dir)
        capsys.readouterr()
        (report_dir / "styles.css").write_text("custom user styles\n")

        assert _ensure_report_templates(report_dir) is True

        assert (report_dir / "styles.css").read_text() == "packaged styles.css\n"
        assert "styles.css" in capsys.readouterr().err

    def test_unchanged_templates_are_not_rewritten(self, tmp_path, monkeypatch, capsys):
        from vip.cli import _REPORT_TEMPLATE_FILES, _ensure_report_templates

        _fake_bundled_templates(monkeypatch, tmp_path)
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        _ensure_report_templates(report_dir)
        sentinel = 946684800  # 2000-01-01, distinct from any freshly written mtime
        for name in _REPORT_TEMPLATE_FILES:
            os.utime(report_dir / name, (sentinel, sentinel))

        assert _ensure_report_templates(report_dir) is True

        for name in _REPORT_TEMPLATE_FILES:
            assert (report_dir / name).stat().st_mtime == sentinel, f"{name} was rewritten"
        assert capsys.readouterr().err == ""

    def test_bundled_lookup_oserror_falls_back_to_checkout(self, tmp_path, monkeypatch):
        import importlib.resources

        from vip.cli import _ensure_report_templates

        def _raise_is_a_directory(path):
            raise IsADirectoryError(str(path))

        # as_file can raise OSError subclasses for zip-imported packages on
        # Python < 3.12; the repo-checkout fallback must still succeed.
        monkeypatch.setattr(importlib.resources, "as_file", _raise_is_a_directory)
        report_dir = tmp_path / "report"
        report_dir.mkdir()

        assert _ensure_report_templates(report_dir) is True


class TestRunReportFromArbitraryDir:
    """run_report works from a directory that is not a source checkout."""

    def test_renders_report_when_results_present(self, tmp_path, monkeypatch, capsys):
        from vip import cli

        monkeypatch.chdir(tmp_path)
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        (report_dir / "results.json").write_text('{"results": []}')
        monkeypatch.setattr(cli.subprocess, "run", _fake_quarto(create_output=True))

        cli.run_report(_make_args())

        assert (report_dir / "index.qmd").is_file()
        assert (report_dir / "_output" / "index.html").is_file()
        assert "Report generated" in capsys.readouterr().out

    def test_errors_when_render_produces_no_output(self, tmp_path, monkeypatch, capsys):
        from vip import cli

        monkeypatch.chdir(tmp_path)
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        (report_dir / "results.json").write_text('{"results": []}')
        # quarto "succeeds" but writes nothing — the old bug rendered silently.
        monkeypatch.setattr(cli.subprocess, "run", _fake_quarto(create_output=False))

        with pytest.raises(SystemExit) as exc:
            cli.run_report(_make_args())

        assert exc.value.code == 1
        assert "no report was produced" in capsys.readouterr().err

    def test_errors_when_results_missing(self, tmp_path, monkeypatch, capsys):
        from vip import cli

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(cli.subprocess, "run", _fake_quarto(create_output=True))

        with pytest.raises(SystemExit) as exc:
            cli.run_report(_make_args(results=str(tmp_path / "nope.json")))

        assert exc.value.code == 1
        assert "results file not found" in capsys.readouterr().err

    def test_errors_when_quarto_not_installed(self, tmp_path, monkeypatch, capsys):
        from vip import cli

        monkeypatch.chdir(tmp_path)
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        (report_dir / "results.json").write_text('{"results": []}')

        def _missing_quarto(cmd, cwd=None, **kwargs):
            raise FileNotFoundError(2, "No such file or directory", cmd[0])

        monkeypatch.setattr(cli.subprocess, "run", _missing_quarto)

        with pytest.raises(SystemExit) as exc:
            cli.run_report(_make_args())

        assert exc.value.code == 1
        assert "quarto was not found" in capsys.readouterr().err


class TestSupportFileResolution:
    """troubleshooting.toml and feature files resolve from checkout or install."""

    def test_troubleshooting_path_resolves(self):
        from vip.reporting import troubleshooting_path

        p = troubleshooting_path()
        assert p is not None and p.exists()
        assert p.name == "troubleshooting.toml"

    def test_feature_file_for_nodeid_resolves_installed_layout(self):
        from vip.reporting import feature_file_for_nodeid

        nodeid = "/opt/x/site-packages/vip_tests/connect/test_auth.py::test_connect_login_ui"
        p = feature_file_for_nodeid(nodeid)
        assert p is not None and p.exists()
        assert p.name == "test_auth.feature"

    def test_feature_file_for_nodeid_returns_none_when_absent(self):
        from vip.reporting import feature_file_for_nodeid

        assert feature_file_for_nodeid("vip_tests/nope/test_missing.py::test_x") is None


class TestReportCLI:
    """``vip report`` is wired into the CLI."""

    def test_report_in_cli_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "vip.cli", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "report" in result.stdout

    def test_report_subcommand_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "vip.cli", "report", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--results" in result.stdout
