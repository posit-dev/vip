"""Traceability matrix: join compliance controls against tagged test results.

VIP stays regulation-agnostic. The control list is supplied by whoever owns the
regulatory mapping; nothing here interprets ``reference``, ``risk`` or
``responsibility`` beyond carrying them through to the output.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from vip.reporting import RESULTS_SCHEMA_VERSION, ReportData

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

# Matrix output schema, versioned independently of results.json.
MATRIX_SCHEMA_VERSION = "1.0"

VERIFICATION_VALUES = frozenset({"automated", "manual", "procedural"})


class ControlListError(Exception):
    """Raised when a controls.toml file is missing or malformed."""


@dataclass
class ControlSpec:
    control_id: str
    description: str
    reference: str | None = None
    risk: str | None = None
    # "automated" controls are expected to be covered by a tagged scenario.
    # "manual" and "procedural" ones are reported as not verifiable by
    # automated test rather than as coverage gaps.
    verification: str = "automated"
    responsibility: str | None = None
    notes: str | None = None


def load_controls(path: str | Path) -> dict[str, ControlSpec]:
    """Load a controls.toml file into ControlSpec objects keyed by control id."""
    p = Path(path)
    if not p.is_file():
        if p.exists():
            raise ControlListError(f"control list {p} is not a file")
        raise ControlListError(f"control list not found: {p}")
    try:
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        raise ControlListError(f"could not read control list {p}: {exc}") from exc

    table = raw.get("controls")
    if not isinstance(table, dict):
        raise ControlListError(f"{p} has no [controls] table")
    if not table:
        raise ControlListError(f"{p} has an empty [controls] table")

    controls: dict[str, ControlSpec] = {}
    for control_id, body in table.items():
        if not isinstance(body, dict):
            raise ControlListError(f"[controls.{control_id}] must be a table")
        description = body.get("description")
        if not isinstance(description, str):
            if description is None:
                raise ControlListError(f"[controls.{control_id}] is missing a description")
            raise ControlListError(
                f"[controls.{control_id}] has description={description!r}; expected a string"
            )
        if not description.strip():
            raise ControlListError(f"[controls.{control_id}] has an empty description")
        verification = body.get("verification", "automated")
        if not isinstance(verification, str):
            raise ControlListError(
                f"[controls.{control_id}] has verification={verification!r}; expected a string"
            )
        if verification not in VERIFICATION_VALUES:
            raise ControlListError(
                f"[controls.{control_id}] has verification={verification!r};"
                f" expected one of {sorted(VERIFICATION_VALUES)}"
            )
        controls[control_id] = ControlSpec(
            control_id=control_id,
            description=description,
            reference=body.get("reference"),
            risk=body.get("risk"),
            verification=verification,
            responsibility=body.get("responsibility"),
            notes=body.get("notes"),
        )
    return controls


@dataclass
class ControlMatch:
    """One scenario that carries a control's tag."""

    nodeid: str
    scenario_title: str | None
    status: str
    started_at: str | None
    finished_at: str | None
    detail: str | None


@dataclass
class ControlEntry:
    control: ControlSpec
    matches: list[ControlMatch] = field(default_factory=list)
    # "covered" | "gap" | "not_automatable"
    coverage: str = "gap"


@dataclass
class TraceabilityMatrix:
    entries: list[ControlEntry] = field(default_factory=list)
    unrecognized_tags: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    schema_version: str = MATRIX_SCHEMA_VERSION

    @property
    def gap_count(self) -> int:
        return sum(1 for e in self.entries if e.coverage == "gap")

    @property
    def covered_count(self) -> int:
        return sum(1 for e in self.entries if e.coverage == "covered")


def _provenance(
    data: ReportData,
    results_sha256: str | None = None,
    results_sha256_sidecar_verified: bool | None = None,
) -> dict:
    products = {
        p.name: {"url": p.url, "version": p.version, "configured": p.configured}
        for p in data.products
    }
    return {
        "generated_at": data.generated_at,
        "deployment_name": data.deployment_name,
        "vip_version": data.vip_version,
        "results_schema_version": data.schema_version,
        "exit_status": data.exit_status,
        # basic_mode is surfaced deliberately: a matrix built from a
        # `vip verify --basic` run omits every @slow scenario and would
        # otherwise assert coverage that was never exercised.
        "basic_mode": data.basic_mode,
        "execution": data.execution,
        # Describes the VIP runner, not the system under test. The products
        # table below identifies the system under test.
        "runner_python_version": data.python_version,
        "runner_platform": data.platform,
        "products": products,
        # The digest `vip trace` computed over the results.json bytes it
        # actually read -- the in-band link between this matrix and the exact
        # evidence file it was derived from. None when the matrix was built
        # without a file on disk (e.g. directly from a ReportData in tests).
        "results_sha256": results_sha256,
        # Tri-state, not a plain bool: True means a `.sha256` sidecar was
        # present and matched (see verify_results_checksum); None means no
        # sidecar existed to check, which is a legal, expected condition for
        # results files written before the sidecar existed -- not a failure.
        # False would mean the sidecar disagreed, but that raises
        # ResultsIntegrityError before a matrix is ever built, so it can
        # never actually appear here.
        "results_sha256_sidecar_verified": results_sha256_sidecar_verified,
    }


def build_traceability_matrix(
    data: ReportData,
    controls: dict[str, ControlSpec],
    tag_prefix: str = "control-",
    results_sha256: str | None = None,
    results_sha256_sidecar_verified: bool | None = None,
) -> TraceabilityMatrix:
    """Join control definitions against tagged test results.

    Sorted deterministically -- by control id, then by nodeid within a control
    -- so the same results.json and control list always produce byte-identical
    output for a downstream renderer to diff.

    ``results_sha256`` / ``results_sha256_sidecar_verified`` carry the
    tamper-evidence digest ``vip trace`` already computed over the results
    file (see ``verify_results_checksum``) into the matrix provenance. Both
    default to ``None`` so a matrix built directly from a ``ReportData`` --
    with no results file on disk, as most tests do -- still works.
    """
    by_tag: dict[str, list[ControlMatch]] = {}
    seen_tags: set[str] = set()
    for result in data.results:
        for marker in result.markers:
            if not marker.startswith(tag_prefix):
                continue
            seen_tags.add(marker)
            by_tag.setdefault(marker, []).append(
                ControlMatch(
                    nodeid=result.nodeid,
                    scenario_title=result.scenario_title,
                    status=result.status,
                    started_at=result.started_at,
                    finished_at=result.finished_at,
                    detail=result.concise_error or result.skip_reason,
                )
            )

    entries: list[ControlEntry] = []
    for control_id in sorted(controls):
        control = controls[control_id]
        matches = sorted(by_tag.get(f"{tag_prefix}{control_id}", []), key=lambda m: m.nodeid)
        if matches:
            coverage = "covered"
        elif control.verification != "automated":
            coverage = "not_automatable"
        else:
            coverage = "gap"
        entries.append(ControlEntry(control=control, matches=matches, coverage=coverage))

    known = {f"{tag_prefix}{cid}" for cid in controls}
    return TraceabilityMatrix(
        entries=entries,
        unrecognized_tags=sorted(seen_tags - known),
        provenance=_provenance(data, results_sha256, results_sha256_sidecar_verified),
    )


CSV_COLUMNS = [
    "control_id",
    "description",
    "reference",
    "risk",
    "verification",
    "responsibility",
    "coverage",
    "scenario",
    "nodeid",
    "status",
    "started_at",
    "finished_at",
    "detail",
    "notes",
]


def _neutralize_formula(value: str) -> str:
    """Prefix leading formula characters with apostrophe to prevent Excel evaluation.

    When a CSV is opened in Excel, a cell starting with =, +, -, or @ is evaluated
    as a formula, which is a security and integrity risk for compliance artifacts.
    The apostrophe forces literal interpretation. This alters the value as seen by
    non-Excel CSV readers (they will see the leading apostrophe); JSON is the format
    to use when exact fidelity matters.

    A leading \\t, \\r, or \\n is included in the dangerous prefix set too: a
    spreadsheet importer commonly strips or normalizes leading control
    characters before evaluating the cell, so "\\t=SUM(1,2)" would otherwise
    reach the sheet as an unescaped formula (OWASP's CSV-injection guidance
    treats these control characters the same as the leading =/+/-/@).
    """
    if value and value[0] in ("=", "+", "-", "@", "\t", "\r", "\n"):
        return "'" + value
    return value


def _control_columns(entry: ControlEntry) -> dict:
    c = entry.control
    return {
        "control_id": c.control_id,
        "description": c.description,
        "reference": c.reference or "",
        "risk": c.risk or "",
        "verification": c.verification,
        "responsibility": c.responsibility or "",
        "coverage": entry.coverage,
        "notes": c.notes or "",
    }


def render_csv(matrix: TraceabilityMatrix) -> str:
    """Render the matrix as CSV: one row per control/scenario pair.

    A control with no matching scenario still gets a row, with the scenario
    columns empty, so a coverage gap is visible rather than absent.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()

    def _neutralize_row(row: dict) -> dict:
        """Apply formula neutralization to all string values in the row."""
        return {k: _neutralize_formula(v) if isinstance(v, str) else v for k, v in row.items()}

    for entry in matrix.entries:
        base = _control_columns(entry)
        if not entry.matches:
            row = {
                **base,
                "scenario": "",
                "nodeid": "",
                "status": "",
                "started_at": "",
                "finished_at": "",
                "detail": "",
            }
            writer.writerow(_neutralize_row(row))
            continue
        for match in entry.matches:
            row = {
                **base,
                "scenario": match.scenario_title or "",
                "nodeid": match.nodeid,
                "status": match.status,
                "started_at": match.started_at or "",
                "finished_at": match.finished_at or "",
                "detail": match.detail or "",
            }
            writer.writerow(_neutralize_row(row))
    return buf.getvalue()


def render_json(matrix: TraceabilityMatrix) -> str:
    """Render the matrix as JSON, carrying the full provenance block."""
    payload = {
        "schema_version": matrix.schema_version,
        "provenance": matrix.provenance,
        "summary": {
            "total": len(matrix.entries),
            "covered": matrix.covered_count,
            "gaps": matrix.gap_count,
            "not_automatable": sum(1 for e in matrix.entries if e.coverage == "not_automatable"),
        },
        "unrecognized_tags": matrix.unrecognized_tags,
        "controls": [
            {
                **_control_columns(entry),
                "matches": [
                    {
                        "nodeid": m.nodeid,
                        "scenario": m.scenario_title,
                        "status": m.status,
                        "started_at": m.started_at,
                        "finished_at": m.finished_at,
                        "detail": m.detail,
                    }
                    for m in entry.matches
                ],
            }
            for entry in matrix.entries
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


class ResultsIntegrityError(Exception):
    """Raised when a results file fails checksum or schema validation."""


def verify_results_checksum(path: str | Path) -> tuple[str, bool]:
    """Verify a results file against its .sha256 sidecar.

    Returns ``(digest, sidecar_present)`` -- the sha256 of the file, and
    whether a `.sha256` sidecar was found to check it against. Raises if a
    sidecar exists and disagrees. A missing sidecar is not an error: results
    files written before the sidecar existed have none, and callers use
    ``sidecar_present`` to distinguish "verified" from "nothing to verify"
    rather than treating both as the same success.

    This is tamper-evidence within a trusted pipeline, not tamper-proofing --
    anyone who can edit the results file can regenerate the sidecar. It catches
    corruption, truncated uploads and casual editing.
    """
    p = Path(path)
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    sidecar = p.with_name(f"{p.name}.sha256")
    if not sidecar.is_file():
        return digest, False
    recorded = sidecar.read_text().split()
    if not recorded:
        # An empty or whitespace-only sidecar is itself the truncated-upload
        # case this function advertises catching. Returning True here would put
        # `results_sha256_sidecar_verified: true` in the provenance block while
        # nothing had actually been compared -- a false attestation in the one
        # field whose entire purpose is attesting that the check happened.
        raise ResultsIntegrityError(
            f"checksum sidecar for {p} is empty; expected a sha256 digest. "
            "Delete it to proceed without verification, or regenerate it."
        )
    if recorded[0] != digest:
        raise ResultsIntegrityError(
            f"checksum mismatch for {p}: sidecar records {recorded[0]}, file hashes to {digest}"
        )
    return digest, True


def read_results_schema_version(path: str | Path) -> str | None:
    """Read the top-level ``schema_version`` out of a results.json file.

    This is deliberately independent of ``load_results``: it must be callable
    (and must raise cleanly) BEFORE ``load_results`` ever touches the file, so
    an incompatible or structurally malformed results file is rejected by the
    schema gate instead of crashing inside ``load_results``' own field
    indexing (`r["nodeid"]`, `r["outcome"]`, ...).
    """
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise ResultsIntegrityError(f"could not read results file {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ResultsIntegrityError(f"could not read results file {p}: not a JSON object")
    schema_version = raw.get("schema_version")
    if schema_version is None:
        return None
    if not isinstance(schema_version, str):
        raise ResultsIntegrityError(
            f"could not read results file {p}: schema_version={schema_version!r} is not a string"
        )
    return schema_version


def check_results_schema(schema_version: str | None) -> None:
    """Refuse an unknown major schema version; accept an unknown minor.

    A file with no schema_version predates versioning and is accepted.
    """
    if not schema_version:
        return
    theirs = schema_version.split(".", 1)[0]
    ours = RESULTS_SCHEMA_VERSION.split(".", 1)[0]
    if theirs != ours:
        raise ResultsIntegrityError(
            f"results.json schema version {schema_version} is not supported by this "
            f"vip (understands {RESULTS_SCHEMA_VERSION}); upgrade vip or regenerate the results"
        )
