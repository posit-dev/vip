"""``vip trace``: join a results file against a control list into a traceability matrix."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vip.errors import ReportError
from vip.report_content import traceability_warnings
from vip.traceability import (
    ControlListError,
    ResultsIntegrityError,
    build_traceability_matrix,
    load_controls,
    render_csv,
    render_json,
    validate_results_file,
)


def _resolve_trace_format(explicit: str | None, out: Path | None) -> str:
    """Pick the matrix output format: explicit flag, then --output suffix, then csv.

    Inferring from the suffix is what stops `--output matrix.json` writing CSV
    bytes into a .json file and reporting success -- the archived artifact then
    fails to parse in whatever downstream consumer reads it, and unlike the
    stdout case the caller never sees the bytes to notice.
    """
    inferred = {".json": "json", ".csv": "csv"}.get(out.suffix.lower()) if out else None
    if explicit is None:
        return inferred or "csv"
    if out is not None and inferred and inferred != explicit:
        print(
            f"Warning: --format {explicit} does not match the {out.suffix} extension of "
            f"{out}; writing {explicit}.",
            file=sys.stderr,
        )
    return explicit


def run_trace(args: argparse.Namespace) -> None:
    """Join a results.json against a control list and emit a traceability matrix."""
    results_path = Path(args.results)
    if not results_path.is_file():
        raise ReportError(f"results file not found: {results_path}")

    try:
        # One read: the digest, the gates and the ReportData all come from the
        # same bytes, so the provenance digest cannot end up describing a file
        # the matrix was not built from. See validate_results_file.
        validated = validate_results_file(results_path)
        controls = load_controls(args.controls)
    except (ResultsIntegrityError, ControlListError) as exc:
        raise ReportError(str(exc)) from exc
    except (OSError, AttributeError, KeyError, TypeError) as exc:
        # A malformed results.json must not surface as a traceback -- this
        # catches structural failures (e.g. {"results": [{}]}) that pass JSON
        # parsing and the gates but fail the row-to-TestResult step's own
        # field indexing.
        raise ReportError(f"could not read results file {results_path}: {exc}") from exc

    out = Path(args.output) if args.output else None
    fmt = _resolve_trace_format(args.format, out)

    try:
        matrix = build_traceability_matrix(
            validated.data,
            controls,
            results_sha256=validated.digest,
            results_sha256_sidecar_verified=validated.sidecar_present or None,
        )
        rendered = render_json(matrix) if fmt == "json" else render_csv(matrix)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        # Inside the guard, not outside it: a results.json can pass the
        # checksum, the schema gate and the load step and still be structurally
        # wrong in a way that only surfaces here -- an explicit `"markers":
        # null`, say. A compliance tool reporting that as a raw traceback is
        # the one presentation that tells an operator nothing.
        raise ReportError(f"could not build the matrix from {results_path}: {exc}") from exc

    if matrix.unrecognized_tags:
        joined = ", ".join(matrix.unrecognized_tags)
        print(
            f"Warning: control tags present in results but absent from the control list: {joined}",
            file=sys.stderr,
        )

    # The three ways a control can count toward "0 gaps" without being
    # evidence: nothing ran, what ran did not pass, or VIP was asked to check
    # it and could not. Taken from report_content, which renders the same
    # three lines into the HTML and PDF editions, so a compliance run cannot
    # word the same finding one way on screen and another in the archived
    # artifact.
    caveats = traceability_warnings(matrix)
    for line in caveats:
        print(f"Warning: {line}", file=sys.stderr)
    if caveats:
        print(
            "Coverage records that a scenario is tagged for a control, not that it "
            "ran or that it passed.",
            file=sys.stderr,
        )

    if out is None:
        sys.stdout.write(rendered)
        return

    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        # Write via a temp file in the destination directory, then replace.
        # `write_text` truncates before it encodes, so a UnicodeEncodeError or
        # a full disk would destroy a previously good matrix at this path.
        tmp = out.with_name(f"{out.name}.tmp")
        tmp.write_text(rendered, encoding="utf-8")
        tmp.replace(out)
    except (OSError, UnicodeError) as exc:
        raise ReportError(f"could not write {out}: {exc}") from exc
    print(
        f"Wrote {out} ({len(matrix.entries)} controls, {matrix.gap_count} gaps, "
        f"{len(matrix.covered_with_failure)} failing, "
        f"{len(matrix.covered_with_unproven)} not verified)"
    )
