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


def _fake_quarto(create_output: bool, pdf_returncode: int = 0):
    """Return a subprocess.run stand-in that fakes the per-document renders.

    run_report renders each listed document with its own
    ``quarto render <doc>`` call, so the stand-in writes the output file the
    named document would produce. ``pdf_returncode`` makes only the
    vip-report.qmd call fail, the shape of a Quarto too old to know Typst.
    """

    def _run(cmd, cwd=None, **kwargs):
        document = cmd[-1]
        if document == "vip-report.qmd" and pdf_returncode != 0:
            return types.SimpleNamespace(returncode=pdf_returncode)
        if create_output and cwd is not None:
            from pathlib import Path

            out = Path(cwd) / "_output"
            out.mkdir(parents=True, exist_ok=True)
            if document == "vip-report.qmd":
                (out / "vip-report.pdf").write_bytes(b"%PDF-fake")
            else:
                (out / (Path(document).stem + ".html")).write_text("<html>report</html>")
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
        (bundled / name).parent.mkdir(parents=True, exist_ok=True)
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
            (report_dir / name).parent.mkdir(parents=True, exist_ok=True)
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

    def test_copy_failure_is_not_swallowed(self, tmp_path, monkeypatch):
        from vip.cli import _ensure_report_templates

        _fake_bundled_templates(monkeypatch, tmp_path)
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        _ensure_report_templates(report_dir)
        stale = report_dir / "index.qmd"
        stale.write_text("stale local copy\n")
        stale.chmod(0o444)

        # A failed refresh must surface rather than silently rendering the
        # stale template set that is already present in report_dir.
        try:
            with pytest.raises(PermissionError):
                _ensure_report_templates(report_dir)
        finally:
            stale.chmod(0o644)

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
        assert (report_dir / "_output" / "vip-report.pdf").is_file()
        out = capsys.readouterr().out
        assert "Report generated" in out
        assert "PDF generated" in out

    def test_does_not_nest_when_already_inside_report_dir(self, tmp_path, monkeypatch, capsys):
        """Running from inside ``report/`` renders in place, not in report/report.

        ``Path("report")`` resolves relative to the invocation, so calling
        ``vip report --results results.json`` from within a report directory
        used to create a nested ``report/report/`` and render there, leaving a
        stray tree behind and hiding the output a level deeper than expected.
        """
        from vip import cli

        report_dir = tmp_path / "report"
        report_dir.mkdir()
        (report_dir / "results.json").write_text('{"results": []}')
        monkeypatch.chdir(report_dir)
        monkeypatch.setattr(cli.subprocess, "run", _fake_quarto(create_output=True))

        cli.run_report(_make_args(results="results.json"))

        assert not (report_dir / "report").exists()
        assert (report_dir / "_output" / "index.html").is_file()
        assert "Report generated" in capsys.readouterr().out

    def test_pins_quarto_python_to_current_interpreter(self, tmp_path, monkeypatch):
        """run_report forces Quarto's kernel to sys.executable (issue #554).

        Quarto otherwise picks Python from the ambient VIRTUAL_ENV or
        /usr/bin/python3, neither guaranteed to have posit-vip + the Jupyter
        stack the report cells import.
        """
        from vip import cli

        monkeypatch.chdir(tmp_path)
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        (report_dir / "results.json").write_text('{"results": []}')

        captured: dict = {}

        def _capture(cmd, cwd=None, env=None, **kwargs):
            captured["env"] = env
            out = Path(cwd) / "_output"
            out.mkdir(parents=True, exist_ok=True)
            (out / "index.html").write_text("<html>report</html>")
            return types.SimpleNamespace(returncode=0)

        # A hostile VIRTUAL_ENV must not win over the explicit pin.
        monkeypatch.setenv("VIRTUAL_ENV", "/some/other/venv")
        monkeypatch.setattr(cli.subprocess, "run", _capture)

        cli.run_report(_make_args())

        assert captured["env"] is not None, "env must be passed to quarto render"
        assert captured["env"]["QUARTO_PYTHON"] == sys.executable

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

    def test_pdf_failure_degrades_to_warning(self, tmp_path, monkeypatch, capsys):
        """A Typst-less Quarto must not cost the user the HTML report.

        Pre-1.4 Quarto has no typst format, so the vip-report.qmd render
        fails. That is the reviewed regression: with one combined render its
        nonzero exit aborted run_report before the HTML hand-off. Rendered
        separately, the HTML report still succeeds and the PDF only warns.
        """
        from vip import cli

        monkeypatch.chdir(tmp_path)
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        (report_dir / "results.json").write_text('{"results": []}')
        monkeypatch.setattr(
            cli.subprocess, "run", _fake_quarto(create_output=True, pdf_returncode=1)
        )

        cli.run_report(_make_args())

        captured = capsys.readouterr()
        assert "Report generated" in captured.out
        assert "PDF generated" not in captured.out
        assert "Warning" in captured.err
        assert "quarto --version" in captured.err

    def test_html_failure_is_fatal_and_skips_the_pdf(self, tmp_path, monkeypatch, capsys):
        from vip import cli

        monkeypatch.chdir(tmp_path)
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        (report_dir / "results.json").write_text('{"results": []}')

        rendered = []

        def _failing_html(cmd, cwd=None, **kwargs):
            rendered.append(cmd[-1])
            return types.SimpleNamespace(returncode=3)

        monkeypatch.setattr(cli.subprocess, "run", _failing_html)

        with pytest.raises(SystemExit) as exc:
            cli.run_report(_make_args())

        assert exc.value.code == 3
        assert rendered == ["index.qmd"], "must stop at the first failed page"


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


class TestReportControls:
    """`vip report --controls` scopes the control list to one render.

    Copying controls.toml into the report directory was the alternative and is
    wrong: that directory survives between runs, so one --controls invocation
    would leave a file behind that every later plain `vip report` picks up,
    growing a compliance section nobody asked for from a stale list.
    """

    @pytest.fixture
    def cli(self):
        from vip import cli

        return cli

    def _args(self, tmp_path, controls=None):
        results = tmp_path / "results.json"
        results.write_text('{"schema_version": "1.0", "results": []}', encoding="utf-8")
        return argparse.Namespace(results=str(results), controls=controls, open=False, output=None)

    def test_malformed_control_list_fails_before_quarto_starts(self, cli, tmp_path, monkeypatch):
        """A notebook cell can only degrade to a warning, so validate out here."""
        monkeypatch.chdir(tmp_path)
        bad = tmp_path / "c.toml"
        bad.write_text("[controls]\n", encoding="utf-8")

        called = []
        monkeypatch.setattr(cli, "_quarto_render", lambda *a, **k: called.append(a) or 0)
        with pytest.raises(SystemExit) as exc:
            cli.run_report(self._args(tmp_path, str(bad)))
        assert exc.value.code == 1
        assert called == []

    def test_missing_control_list_fails_before_quarto_starts(self, cli, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        called = []
        monkeypatch.setattr(cli, "_quarto_render", lambda *a, **k: called.append(a) or 0)
        with pytest.raises(SystemExit):
            cli.run_report(self._args(tmp_path, str(tmp_path / "absent.toml")))
        assert called == []

    def test_controls_reach_both_renders_through_the_environment(self, cli, tmp_path, monkeypatch):
        """The HTML pages and the PDF are separate quarto invocations."""
        monkeypatch.chdir(tmp_path)
        controls = tmp_path / "c.toml"
        controls.write_text('[controls.x]\ndescription = "d"\n', encoding="utf-8")

        envs = []

        def fake_render(document, report_dir, env):
            envs.append((document, env.get("VIP_CONTROLS")))
            out = report_dir / "_output"
            out.mkdir(parents=True, exist_ok=True)
            (out / "index.html").write_text("<html></html>")
            (out / "vip-report.pdf").write_bytes(b"%PDF-")
            return 0

        monkeypatch.setattr(cli, "_quarto_render", fake_render)
        cli.run_report(self._args(tmp_path, str(controls)))

        rendered = dict(envs)
        assert rendered["index.qmd"] == str(controls.resolve())
        assert rendered["vip-report.qmd"] == str(controls.resolve())

    def _results(self, tmp_path, body):
        results = tmp_path / "results.json"
        results.write_text(body, encoding="utf-8")
        return results

    def _fake_render(self, envs):
        def render(document, report_dir, env):
            envs.append((document, env.get("VIP_CONTROLS")))
            out = report_dir / "_output"
            out.mkdir(parents=True, exist_ok=True)
            (out / "index.html").write_text("<html></html>")
            (out / "vip-report.pdf").write_bytes(b"%PDF-")
            return 0

        return render

    _UNREADABLE_MARKERS = (
        '{"schema_version": "1.0", "results": '
        '[{"nodeid": "t", "outcome": "passed", "markers": null}]}'
    )

    def test_unreadable_markers_are_refused_on_a_compliance_render(
        self, cli, tmp_path, monkeypatch
    ):
        """A row whose markers cannot be read would print a GAP that does not exist.

        `load_results` normalizes a malformed `markers` to an empty list so the
        plain report still renders. Under --controls that turns a tagged
        scenario into a coverage gap, so the matrix claims the suite is missing
        a check it actually has. Refuse the file instead, the way `vip trace`
        does.
        """
        monkeypatch.chdir(tmp_path)
        controls = tmp_path / "c.toml"
        controls.write_text('[controls.x]\ndescription = "d"\n', encoding="utf-8")
        results = self._results(tmp_path, self._UNREADABLE_MARKERS)

        called = []
        monkeypatch.setattr(cli, "_quarto_render", lambda *a, **k: called.append(a) or 0)
        args = argparse.Namespace(
            results=str(results), controls=str(controls), open=False, output=None
        )
        with pytest.raises(SystemExit) as exc:
            cli.run_report(args)
        assert exc.value.code == 1
        assert called == []

    def test_unknown_schema_major_is_refused_on_a_compliance_render(
        self, cli, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        controls = tmp_path / "c.toml"
        controls.write_text('[controls.x]\ndescription = "d"\n', encoding="utf-8")
        results = self._results(tmp_path, '{"schema_version": "99.0", "results": []}')

        called = []
        monkeypatch.setattr(cli, "_quarto_render", lambda *a, **k: called.append(a) or 0)
        args = argparse.Namespace(
            results=str(results), controls=str(controls), open=False, output=None
        )
        with pytest.raises(SystemExit) as exc:
            cli.run_report(args)
        assert exc.value.code == 1
        assert called == []

    def test_the_same_file_still_renders_without_controls(self, cli, tmp_path, monkeypatch):
        """The asymmetry is the design, not an oversight.

        Without a control list the report is a pass/fail document and must
        render regardless -- the strictness above belongs to the compliance
        artifact, not to every render.
        """
        monkeypatch.chdir(tmp_path)
        results = self._results(tmp_path, self._UNREADABLE_MARKERS)

        envs = []
        monkeypatch.setattr(cli, "_quarto_render", self._fake_render(envs))
        args = argparse.Namespace(results=str(results), controls=None, open=False, output=None)
        cli.run_report(args)

        assert [document for document, _ in envs] == ["index.qmd", "details.qmd", "vip-report.qmd"]

    def test_without_controls_the_variable_is_absent_and_nothing_warns(
        self, cli, tmp_path, monkeypatch, capsys
    ):
        """The overwhelmingly common path: no control list, no section, no noise."""
        monkeypatch.chdir(tmp_path)
        envs = []

        def fake_render(document, report_dir, env):
            envs.append(env.get("VIP_CONTROLS"))
            out = report_dir / "_output"
            out.mkdir(parents=True, exist_ok=True)
            (out / "index.html").write_text("<html></html>")
            (out / "vip-report.pdf").write_bytes(b"%PDF-")
            return 0

        monkeypatch.setattr(cli, "_quarto_render", fake_render)
        cli.run_report(self._args(tmp_path, None))

        assert envs == [None, None, None]
        assert "controls" not in capsys.readouterr().out.lower()

    def test_report_with_controls_refuses_a_mismatched_sidecar(
        self, cli, tmp_path, monkeypatch, capsys
    ):
        """--controls makes this a compliance artifact; it inherits trace's strictness.

        `vip trace` already refuses a results.json whose sidecar disagrees
        (`verify_results_checksum`); a compliance render must refuse the same
        way rather than silently rendering a matrix built from evidence that
        does not match its own attestation.
        """
        monkeypatch.chdir(tmp_path)
        controls = tmp_path / "c.toml"
        controls.write_text('[controls.x]\ndescription = "d"\n', encoding="utf-8")
        results = self._results(tmp_path, '{"schema_version": "1.0", "results": []}')
        results.with_name("results.json.sha256").write_text(f"{'a' * 64}  results.json\n")

        called = []
        monkeypatch.setattr(cli, "_quarto_render", lambda *a, **k: called.append(a) or 0)
        args = argparse.Namespace(
            results=str(results), controls=str(controls), open=False, output=None
        )
        with pytest.raises(SystemExit) as exc:
            cli.run_report(args)

        assert exc.value.code == 1
        assert called == []
        assert "checksum mismatch" in capsys.readouterr().err

    def test_report_with_controls_refuses_an_empty_source_sidecar(
        self, cli, tmp_path, monkeypatch, capsys
    ):
        """An invalid attestation must not launder itself into a benign absence.

        `--results /external/path/results.json` copies the file into the
        report directory, and _rehome_sidecar correctly refuses to
        manufacture a destination sidecar out of an empty source one. A
        *missing* destination sidecar is legal and benign, so a gate that
        only ever looked at the destination let the compliance render
        proceed on input `vip trace` refuses as a truncated attestation.
        The compliance path must never be more permissive than `vip trace`.
        """
        monkeypatch.chdir(tmp_path)
        external = tmp_path / "external"
        external.mkdir()
        results = external / "results.json"
        results.write_text('{"schema_version": "1.0", "results": []}', encoding="utf-8")
        results.with_name("results.json.sha256").write_text("   \n\n", encoding="utf-8")

        controls = tmp_path / "c.toml"
        controls.write_text('[controls.x]\ndescription = "d"\n', encoding="utf-8")

        called = []
        monkeypatch.setattr(cli, "_quarto_render", lambda *a, **k: called.append(a) or 0)
        args = argparse.Namespace(
            results=str(results), controls=str(controls), open=False, output=None
        )
        with pytest.raises(SystemExit) as exc:
            cli.run_report(args)

        assert exc.value.code == 1
        assert called == []
        assert "is empty" in capsys.readouterr().err

    def test_the_same_empty_sidecar_still_renders_without_controls(
        self, cli, tmp_path, monkeypatch
    ):
        """Plain `vip report` stays lenient; only the compliance path is strict."""
        monkeypatch.chdir(tmp_path)
        external = tmp_path / "external"
        external.mkdir()
        results = external / "results.json"
        results.write_text('{"schema_version": "1.0", "results": []}', encoding="utf-8")
        results.with_name("results.json.sha256").write_text("   \n\n", encoding="utf-8")

        envs = []
        monkeypatch.setattr(cli, "_quarto_render", self._fake_render(envs))
        args = argparse.Namespace(results=str(results), controls=None, open=False, output=None)
        cli.run_report(args)

        assert [document for document, _ in envs] == ["index.qmd", "details.qmd", "vip-report.qmd"]
        assert not (tmp_path / "report" / "results.json.sha256").exists()

    def test_a_source_with_no_sidecar_at_all_is_still_benign_under_controls(
        self, cli, tmp_path, monkeypatch
    ):
        """No sidecar is a documented benign state on both paths.

        Results files written before the sidecar existed have none, and
        `vip trace` accepts them; the compliance render must match rather
        than exceed that strictness.
        """
        monkeypatch.chdir(tmp_path)
        external = tmp_path / "external"
        external.mkdir()
        results = external / "results.json"
        results.write_text('{"schema_version": "1.0", "results": []}', encoding="utf-8")

        controls = tmp_path / "c.toml"
        controls.write_text('[controls.x]\ndescription = "d"\n', encoding="utf-8")

        envs = []
        monkeypatch.setattr(cli, "_quarto_render", self._fake_render(envs))
        args = argparse.Namespace(
            results=str(results), controls=str(controls), open=False, output=None
        )
        cli.run_report(args)

        assert [document for document, _ in envs] == ["index.qmd", "details.qmd", "vip-report.qmd"]

    def test_report_without_controls_ignores_a_mismatched_sidecar(self, cli, tmp_path, monkeypatch):
        """Plain vip report stays lenient: a report must render regardless.

        This is the other half of the asymmetry: the checksum gate must live
        inside the `if args.controls` block, not ahead of it, or a plain
        render would refuse to produce anything from a perfectly good local
        results.json just because its stale sidecar disagrees.
        """
        monkeypatch.chdir(tmp_path)
        results = self._results(tmp_path, '{"schema_version": "1.0", "results": []}')
        results.with_name("results.json.sha256").write_text(f"{'a' * 64}  results.json\n")

        envs = []
        monkeypatch.setattr(cli, "_quarto_render", self._fake_render(envs))
        args = argparse.Namespace(results=str(results), controls=None, open=False, output=None)

        cli.run_report(args)

        assert [document for document, _ in envs] == [
            "index.qmd",
            "details.qmd",
            "vip-report.qmd",
        ]
