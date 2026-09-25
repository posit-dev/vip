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
from vip.traceability import (
    ControlListError,
    ResultsIntegrityError,
    load_controls,
    validate_results_file,
    verify_results_checksum,
)

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


def _rehome_sidecar(results_src: Path, results_dest: Path) -> str | None:
    """Move a checksum sidecar alongside a copied results file.

    Returns ``None`` when the destination ends up with the attestation the
    source had, or the reason there was none to carry, which the caller
    reports. A stale destination sidecar is always removed either way: no
    sidecar is a documented benign state, a wrong one is a false tamper alarm.

    A sidecar that verifies its source is rewritten as the one line VIP
    writes, under the destination name, so a source called run-42.json still
    verifies once copied to results.json. Writing the verified digest is not
    the same as recomputing one from the copy: the digest went through
    ``verify_results_checksum`` against the source bytes first, so a tampered
    file never reaches this branch to be laundered into a verified one.

    A sidecar that does *not* verify its source attested to nothing, so
    nothing is carried across. Copying it through was the obvious alternative
    and is wrong, because the rename can repair it: a sidecar recording the
    source's correct digest under the name ``results.json`` fails at a source
    called ``run-42.json`` and then *verifies* once sat beside the copy, which
    is exactly the false attestation the single-entry grammar exists to
    prevent. Reporting the reason to the caller keeps the failure visible
    where an operator reads it, at copy time, rather than deferring it to
    whatever runs `vip trace` next.
    """
    src = results_src.with_name(f"{results_src.name}.sha256")
    dest = results_dest.with_name(f"{results_dest.name}.sha256")
    if not src.is_file():
        dest.unlink(missing_ok=True)
        return None
    try:
        digest, _ = verify_results_checksum(results_src)
    except ResultsIntegrityError as exc:
        dest.unlink(missing_ok=True)
        return str(exc)
    dest.write_text(f"{digest}  {results_dest.name}\n", encoding="utf-8")
    return None


def run_report(args: argparse.Namespace) -> None:
    """Render the Quarto report from a results.json file."""
    report_dir = _resolve_report_dir()
    report_dir.mkdir(parents=True, exist_ok=True)

    results_src = Path(args.results)
    results_dest = report_dir / "results.json"

    if results_src.resolve() != results_dest.resolve():
        if not results_src.exists():
            raise ReportError(f"results file not found: {results_src}")
        if getattr(args, "controls", None):
            # Verify the SOURCE before the copy, not only the destination
            # after it. _rehome_sidecar is right to discard an empty or
            # unreadable source sidecar rather than manufacture one at the
            # destination -- but a missing destination sidecar is legal and
            # benign, so the gate below would then wave through the very
            # input `vip trace` refuses as a truncated attestation. The
            # compliance render must never be more permissive than
            # `vip trace` on identical bytes. A source with genuinely no
            # sidecar stays benign here, exactly as it is for `vip trace`.
            try:
                verify_results_checksum(results_src)
            except ResultsIntegrityError as exc:
                raise ReportError(str(exc)) from exc
            except (OSError, UnicodeDecodeError) as exc:
                raise ReportError(f"could not read results file {results_src}: {exc}") from exc
        shutil.copy2(results_src, results_dest)
        # Keep the checksum sidecar with the results it describes. Copying a
        # results.json from a CI artifact over the local one leaves the
        # previous run's sidecar in place, and the next `vip trace` then
        # reports a checksum mismatch on a file nobody tampered with. Carry
        # the source's sidecar across when it has one; otherwise remove the
        # stale local one, because no sidecar is a documented benign state
        # and a wrong one is a false tamper alarm.
        dest_sidecar = results_dest.with_name(f"{results_dest.name}.sha256")
        try:
            unattested = _rehome_sidecar(results_src, results_dest)
        except OSError as exc:
            print(f"Warning: could not update {dest_sidecar}: {exc}", file=sys.stderr)
        else:
            if unattested:
                # Not an error: a plain `vip report` renders whatever it is
                # given, and `--controls` already exited above on this input.
                # But the operator asked to copy a file whose sidecar does not
                # describe it, so say so here rather than let it surface later
                # as a tamper alarm from `vip trace` on the copy.
                print(
                    f"Warning: the checksum sidecar beside {results_src} does not "
                    f"verify it ({unattested}) Copied {results_dest.name} without one.",
                    file=sys.stderr,
                )
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

    # Scope the control list to this render via the environment. Copying
    # controls.toml into the report directory was the obvious alternative and
    # is wrong: that directory survives between runs, so one
    # `vip report --controls ...` would leave a file behind that every later
    # plain `vip report` silently picks up, growing a compliance section
    # nobody asked for out of a stale list. Validate it here so a malformed
    # file fails before Quarto starts, rather than inside a notebook cell
    # where the .qmd can only degrade to a warning.
    if getattr(args, "controls", None):
        controls_path = Path(args.controls).resolve()
        try:
            # --controls turns the report into a compliance artifact, so it
            # inherits `vip trace`'s strictness about its evidence, through the
            # same entry point. Plain `vip report` stays lenient on purpose:
            # `load_results` normalizes a malformed `markers` to an empty list
            # and only warns on an unknown schema major, because a report must
            # render regardless. That leniency is wrong here for one specific
            # reason -- a row whose markers cannot be read looks untagged, so
            # the control it was tagged for is printed as a GAP that does not
            # exist, and the matrix claims the suite is missing a check it
            # actually has. Validating the control list here too means a
            # malformed one fails before Quarto starts, rather than inside a
            # notebook cell that can only degrade to a visible marker.
            validate_results_file(results_dest)
            load_controls(controls_path)
        except (ResultsIntegrityError, ControlListError) as exc:
            raise ReportError(str(exc)) from exc
        except (OSError, UnicodeDecodeError) as exc:
            # A results file that cannot even be read must not reach the user
            # as a traceback.
            raise ReportError(f"could not read results file {results_dest}: {exc}") from exc
        env["VIP_CONTROLS"] = str(controls_path)

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
