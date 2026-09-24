"""``vip report``: render the Quarto report from a results file."""

from __future__ import annotations

import argparse
import contextlib
import importlib.resources
import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path

from vip.errors import ReportError

# Quarto report template files copied into the working report/ directory.
# Keep in sync with the force-include block in pyproject.toml. The fonts are
# part of the template set: vip-report.qmd resolves them via a relative
# `font-paths: fonts`, so a working report directory without them falls back
# to whatever faces the host has and renders a different-looking PDF.
_REPORT_TEMPLATE_FILES = (
    "index.qmd",
    "details.qmd",
    "vip-report.qmd",
    "_quarto.yml",
    "styles.css",
    "fonts/SourceSans3-Regular.otf",
    "fonts/SourceSans3-It.otf",
    "fonts/SourceSans3-Semibold.otf",
    "fonts/SourceSans3-Bold.otf",
    "fonts/SourceCodePro-Regular.otf",
    "fonts/LICENSE-SourceSans3.md",
    "fonts/LICENSE-SourceCodePro.md",
)


def _has_all_report_templates(directory: Path) -> bool:
    """Whether ``directory`` contains every required Quarto template file."""
    return all((directory / name).is_file() for name in _REPORT_TEMPLATE_FILES)


def _copy_report_templates(src: Path, report_dir: Path) -> list[str]:
    """Copy template files from ``src``, returning names whose content changed.

    Files already identical in ``report_dir`` are left untouched, and only
    pre-existing files that were overwritten with different content are
    reported (fresh copies into an empty directory are not).
    """
    replaced = []
    for name in _REPORT_TEMPLATE_FILES:
        candidate = src / name
        dest = report_dir / name
        if not candidate.is_file():
            continue
        if dest.is_file():
            if dest.read_bytes() == candidate.read_bytes():
                continue
            replaced.append(name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, dest)
    return replaced


def _ensure_report_templates(report_dir: Path) -> bool:
    """Make sure the Quarto templates exist in ``report_dir``.

    Prefers the copy bundled in the installed wheel (``vip/_report``),
    refreshing ``report_dir`` from it on every run so an upgraded VIP renders
    its current templates. Falls back to the repo's top-level ``report/`` so
    in-repo usage and selftests work without building a wheel. Returns ``True``
    only when *all* of ``_REPORT_TEMPLATE_FILES`` are present in ``report_dir``,
    so a partial source (e.g. a template missing from one location) is topped
    up from the other rather than silently rendering a degraded report.

    Identical files are not rewritten, and a notice lists any existing files
    that the refresh did overwrite, so local template customizations never
    disappear silently.
    """
    replaced: list[str] = []

    # Bundled wheel copy: refresh templates into the working directory. Only
    # materializing the resource is guarded (OSError covers as_file() failures
    # on zip-imported packages before Python 3.12); a failure while copying
    # into report_dir must propagate, or a stale set already present there
    # would be rendered as if it were current.
    with contextlib.ExitStack() as stack:
        try:
            bundled = importlib.resources.files("vip") / "_report"
            p = stack.enter_context(importlib.resources.as_file(bundled))
        except (TypeError, OSError, ModuleNotFoundError):
            p = None
        if p is not None and _has_all_report_templates(p):
            replaced += _copy_report_templates(p, report_dir)

    # Source checkout: four levels up from src/vip/cli/report.py → repo root/report.
    if not _has_all_report_templates(report_dir):
        repo_report = Path(__file__).parent.parent.parent.parent / "report"
        if _has_all_report_templates(repo_report) and repo_report.resolve() != report_dir.resolve():
            replaced += _copy_report_templates(repo_report, report_dir)

    if replaced:
        print(
            f"Refreshed report templates in {report_dir}: {', '.join(replaced)}",
            file=sys.stderr,
        )

    # True only if the working directory now has the complete set (from a
    # bundled/repo copy above, or from a prior run's copy already present).
    return _has_all_report_templates(report_dir)


def _resolve_report_dir() -> Path:
    """Return the working report directory for the current invocation.

    The report directory is ``./report`` relative to the invocation, but a
    plain ``Path("report")`` also resolves that way when the caller is already
    standing *inside* a report directory. Treat a working directory already
    named ``report`` as the report directory itself, instead of descending
    into it: otherwise ``vip report --results results.json`` run from within
    ``report/`` creates a nested ``report/report/``, copies the templates
    into it, and renders there, leaving a stray tree behind (papered over by
    a ``report/report/`` .gitignore entry) and hiding the rendered output one
    level deeper than the caller expected.
    """
    cwd = Path.cwd()
    if cwd.name == "report":
        return Path()
    return Path("report")


def run_report(args: argparse.Namespace) -> None:
    """Render the Quarto report from a results.json file."""
    report_dir = _resolve_report_dir()
    report_dir.mkdir(parents=True, exist_ok=True)

    results_src = Path(args.results)
    results_dest = report_dir / "results.json"

    if results_src.resolve() != results_dest.resolve():
        if not results_src.exists():
            raise ReportError(f"results file not found: {results_src}")
        shutil.copy2(results_src, results_dest)
    elif not results_dest.exists():
        raise ReportError(
            f"no results found at {results_dest}. Run 'vip verify' first, or pass --results PATH."
        )

    if not _ensure_report_templates(report_dir):
        raise ReportError(
            "could not locate the VIP report templates. "
            "Reinstall posit-vip so the bundled report is available."
        )

    # Pin Quarto's Jupyter kernel to the interpreter running `vip`. Quarto
    # otherwise discovers Python via the ambient VIRTUAL_ENV (set by `uv run`
    # or an activated venv) or falls back to /usr/bin/python3 -- neither of
    # which is guaranteed to have posit-vip (for the report/*.qmd cells that
    # import vip.gherkin / vip.reporting) or the Jupyter stack. sys.executable
    # is the vip install itself, which always has both. See issue #554.
    env = {**os.environ, "QUARTO_PYTHON": sys.executable}

    # The HTML pages and the PDF render as separate quarto invocations on
    # purpose. One combined `quarto render` ties their fates together: on a
    # Quarto too old to know Typst (pre-1.4), the PDF document fails the
    # whole render *after* the HTML pages already rendered, and `vip report`
    # would exit nonzero without handing over the HTML report it just
    # produced. HTML is the primary artifact, so only its failure is fatal;
    # the PDF degrades to a warning. All three documents stay in
    # _quarto.yml's render list because a single-document render only lands
    # in _output/ for listed files.
    for page in ("index.qmd", "details.qmd"):
        returncode = _quarto_render(page, report_dir, env)
        if returncode != 0:
            sys.exit(returncode)

    output = report_dir / "_output" / "index.html"
    if not output.exists():
        raise ReportError(
            "no report was produced. Ensure Quarto is installed "
            "(https://quarto.org/docs/get-started/) and re-run."
        )

    print(f"Report generated: {output}")

    # The PDF is the copy customers archive, so a missing one warns loudly —
    # but never fails the command, and never blocks the HTML hand-off above.
    pdf = report_dir / "_output" / "vip-report.pdf"
    if _quarto_render("vip-report.qmd", report_dir, env) == 0 and pdf.exists():
        print(f"PDF generated: {pdf}")
    else:
        print(
            f"Warning: the HTML report rendered but {pdf} did not. "
            "Quarto compiles it with Typst, which ships with Quarto 1.4 and "
            "later — check `quarto --version` and upgrade if it is older.",
            file=sys.stderr,
        )

    if args.open:
        webbrowser.open(output.resolve().as_uri())


def _quarto_render(document: str, report_dir: Path, env: dict[str, str]) -> int:
    """Render one listed document of the report project, returning quarto's exit code.

    A missing quarto binary is fatal here rather than at the caller: it means
    no document can render at all, and the message is the same wherever it
    surfaces.
    """
    try:
        result = subprocess.run(
            ["quarto", "render", document], cwd=str(report_dir), env=env, check=False
        )
    except FileNotFoundError:
        raise ReportError(
            "quarto was not found on PATH. Install Quarto "
            "(https://quarto.org/docs/get-started/) and re-run."
        ) from None
    return result.returncode
