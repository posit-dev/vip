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
from pathlib import Path, PurePosixPath

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
    # Free-form pass-through columns from [controls.<id>.extra]. A regulated
    # customer's control list is their own regulatory mapping, and the fields
    # above cannot anticipate it -- IQ/OQ/PQ phase, a SOP reference, a control
    # owner. These reach the CSV and JSON exports verbatim and are not
    # rendered in the report, whose table has no width for a variable number
    # of columns. Nothing here is interpreted.
    extra: dict[str, str] = field(default_factory=dict)


# Every key a [controls.<id>] table may carry. Anything else is rejected
# rather than ignored -- see the error raised in load_controls for why.
_KNOWN_CONTROL_KEYS = frozenset(
    {"description", "reference", "risk", "verification", "responsibility", "notes", "extra"}
)


def _load_extra(control_id: str, body: dict) -> dict[str, str]:
    """Validate and return the [controls.<id>.extra] pass-through table.

    Values must be strings for the same reason the built-in pass-through
    fields must: TOML has native date and integer types, and a bare
    ``2024-01-01`` becomes a ``datetime.date`` that the CSV writer silently
    stringifies while the JSON encoder refuses outright.

    A key that collides with a built-in column is rejected rather than
    silently shadowed or duplicated: ``extra.risk`` would otherwise emit two
    ``risk`` columns in the CSV, and a spreadsheet reader would take whichever
    it saw last.
    """
    raw = body.get("extra")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ControlListError(f"[controls.{control_id}.extra] must be a table")
    extra: dict[str, str] = {}
    for key, value in raw.items():
        if key in CSV_COLUMNS:
            raise ControlListError(
                f"[controls.{control_id}.extra] has key {key!r}, which is already a "
                "column in the exported matrix. Choose another name."
            )
        if not isinstance(value, str):
            raise ControlListError(
                f"[controls.{control_id}.extra] has {key}={value!r} "
                f"({type(value).__name__}); expected a string. Quote it if it is a "
                "date or a number."
            )
        extra[key] = value
    return extra


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
        # The pass-through fields are carried verbatim into both renderers, so
        # they must be validated here rather than at render time. TOML has
        # native date and integer types: `reference = 2024-01-01` parses to a
        # datetime.date, which the CSV writer silently stringifies while the
        # JSON encoder refuses outright. Rejecting it once, here, is what keeps
        # the two formats agreeing on what counts as a valid control list.
        optional = {}
        for field_name in ("reference", "risk", "responsibility", "notes"):
            value = body.get(field_name)
            if value is not None and not isinstance(value, str):
                raise ControlListError(
                    f"[controls.{control_id}] has {field_name}={value!r} "
                    f"({type(value).__name__}); expected a string. Quote it if it is a "
                    "date or a number."
                )
            optional[field_name] = value
        extra = _load_extra(control_id, body)
        unknown = set(body) - _KNOWN_CONTROL_KEYS
        if unknown:
            # Silently dropping these was worse than either alternative: a
            # customer who wrote `phase = "OQ"` got no error and no column, and
            # a typo like `referance` vanished the same way -- from a file
            # whose whole job is to be the regulatory mapping of record.
            raise ControlListError(
                f"[controls.{control_id}] has unknown "
                f"{'keys' if len(unknown) > 1 else 'key'} {', '.join(sorted(unknown))}. "
                f"Known keys are {', '.join(sorted(_KNOWN_CONTROL_KEYS))}. "
                f"Put your own fields in [controls.{control_id}.extra]; they are "
                "carried into the CSV and JSON exports untouched."
            )
        controls[control_id] = ControlSpec(
            extra=extra,
            control_id=control_id,
            description=description,
            verification=verification,
            **optional,
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


# Statuses that mean the check did not run. "na_version" is a
# version-gated non-execution, so it counts here too: treating it as
# executed would let a control gated off on an older product read as
# evidenced by a scenario that never ran a single assertion.
NON_EXECUTING_STATUSES = frozenset({"skipped", "na_version"})


@dataclass
class ControlEntry:
    control: ControlSpec
    matches: list[ControlMatch] = field(default_factory=list)
    # "covered" | "gap" | "not_automatable"
    coverage: str = "gap"

    @property
    def executed(self) -> bool:
        """Whether any tagged scenario actually ran.

        Coverage says a scenario is tagged for this control. This says one of
        them produced a result. The two come apart when a scenario runs and
        skips itself (an absent endpoint, no data to inspect, a version gate),
        because the result row it writes still lists its control tag, so a
        matrix reads covered for a check that verified nothing. An
        unconfigured product is the opposite case:
        ``plugin.pytest_collection_modifyitems`` deselects those scenarios, so
        they never reach ``results.json`` and a control tagged *only* by them
        reports as a gap.
        """
        return any(m.status not in NON_EXECUTING_STATUSES for m in self.matches)

    @property
    def failing(self) -> bool:
        """Whether any tagged scenario produced a result that was not a pass.

        The third fact about a control, after "a scenario is tagged"
        (``coverage``) and "a scenario ran" (``executed``). Without it a
        control whose only scenario failed reports as covered and executed,
        which is true and reads as evidence.

        Defined by exclusion rather than by enumerating failure statuses:
        ``error`` is a reachable outcome alongside ``failed``, and an
        enumerated list would let an errored control read as evidenced.
        Non-executing statuses are excluded via ``NON_EXECUTING_STATUSES``, so
        a skip alongside a pass never counts against a control.
        """
        return any(
            m.status not in NON_EXECUTING_STATUSES and m.status != "passed" for m in self.matches
        )


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

    @property
    def covered_without_execution(self) -> list[str]:
        """Control ids that are covered but whose every scenario was skipped.

        The headline summary reports these as covered with zero gaps, which
        is true and, on its own, badly misleading: nothing was verified. The
        caller surfaces this so a reader cannot take a green matrix at face
        value when every scenario behind it ran and skipped itself.
        """
        return [
            e.control.control_id for e in self.entries if e.coverage == "covered" and not e.executed
        ]

    @property
    def covered_with_failure(self) -> list[str]:
        """Control ids that are covered but whose scenarios did not all pass.

        The mirror of ``covered_without_execution``. That one catches a matrix
        that is green because nothing ran; this one catches a matrix that is
        green because a run that did happen was not a success. Any failing
        scenario qualifies the control, not only an all-failed one: a green
        badge above a visible failing scenario row is the misreading this
        exists to prevent.
        """
        return [e.control.control_id for e in self.entries if e.coverage == "covered" and e.failing]


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
    # Provenance, repeated on every row. CSV is the default format and the one
    # that gets archived into a spreadsheet, so without these the artifact a
    # reviewer actually holds has no link back to the results file it was
    # derived from. results_sha256 is that link. The full block -- products
    # under test, host, CI run -- is JSON only, because it does not flatten
    # into columns.
    "generated_at",
    "vip_version",
    "results_sha256",
    "exit_status",
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


def _provenance_columns(matrix: TraceabilityMatrix) -> dict:
    prov = matrix.provenance
    return {
        "generated_at": prov.get("generated_at") or "",
        "vip_version": prov.get("vip_version") or "",
        "results_sha256": prov.get("results_sha256") or "",
        "exit_status": "" if prov.get("exit_status") is None else str(prov["exit_status"]),
    }


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
    # Extra columns append after the fixed set rather than slotting in beside
    # the control metadata they belong with: CSV_COLUMNS then stays an
    # identical leading prefix across every customer's export, whatever their
    # own control list carries. Union across all controls, sorted, so a
    # control that omits a key gets an empty cell rather than a ragged row.
    extra_columns = sorted({k for e in matrix.entries for k in e.control.extra})
    writer = csv.DictWriter(buf, fieldnames=[*CSV_COLUMNS, *extra_columns], lineterminator="\n")
    writer.writeheader()
    prov = _provenance_columns(matrix)
    blank_extra = dict.fromkeys(extra_columns, "")

    def _neutralize_row(row: dict) -> dict:
        """Apply formula neutralization to all string values in the row."""
        return {k: _neutralize_formula(v) if isinstance(v, str) else v for k, v in row.items()}

    for entry in matrix.entries:
        base = {**_control_columns(entry), **blank_extra, **entry.control.extra}
        if not entry.matches:
            row = {
                **base,
                **prov,
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
                **prov,
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
            # Coverage counts controls that have a tagged scenario. This
            # counts controls whose scenario actually ran. The two diverge
            # when a tagged scenario runs and skips itself, which is exactly
            # when a green matrix means least.
            "covered_and_executed": sum(
                1 for e in matrix.entries if e.coverage == "covered" and e.executed
            ),
            "covered_not_executed": len(matrix.covered_without_execution),
            # Covered and executed, but not a success. The third way a green
            # matrix can mislead, after "nothing is tagged" and "nothing ran".
            "covered_failed": len(matrix.covered_with_failure),
        },
        "covered_without_execution": matrix.covered_without_execution,
        "unrecognized_tags": matrix.unrecognized_tags,
        "controls": [
            {
                **_control_columns(entry),
                "extra": entry.control.extra,
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

    Also raises when the entries selected for this file disagree with each
    other: a sidecar that records two different digests under the same name
    cannot attest to anything, so accepting the file because one of them
    happens to match would be a false attestation.

    This is tamper-evidence within a trusted pipeline, not tamper-proofing --
    anyone who can edit the results file can regenerate the sidecar. It catches
    corruption, truncated uploads and casual editing.
    """
    p = Path(path)
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    sidecar = p.with_name(f"{p.name}.sha256")
    if not sidecar.is_file():
        return digest, False
    try:
        text = sidecar.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ResultsIntegrityError(f"could not read checksum sidecar {sidecar}: {exc}") from exc

    entries = _parse_sidecar(text)
    if not entries:
        # An empty or whitespace-only sidecar is itself the truncated-upload
        # case this function advertises catching. Returning True here would put
        # `results_sha256_sidecar_verified: true` in the provenance block while
        # nothing had actually been compared -- a false attestation in the one
        # field whose entire purpose is attesting that the check happened.
        raise ResultsIntegrityError(
            f"checksum sidecar for {p} is empty; expected a sha256 digest. "
            "Delete it to proceed without verification, or regenerate it."
        )

    # Match on the recorded filename rather than taking the first line. A
    # sidecar may legitimately cover several files (`shasum -a 256 a b > s`),
    # and without this the first line's digest is compared against a file it
    # does not describe -- a mismatch on a good file, or, when the digests
    # happen to agree, `results_sha256_sidecar_verified: true` attesting to a
    # comparison against some other file entirely.
    named = [d for d, name in entries if name == p.name]
    if not named:
        # Fall back to comparing basenames. `shasum -a 256 report/results.json`
        # run from a directory above the file records the path it was given
        # rather than the bare name, and refusing that sidecar reads to an
        # operator as a tamper alarm on a file nobody touched. Exact match
        # stays the primary key, so a multi-file sidecar that already names
        # this file exactly never reaches here and keeps its strict behaviour.
        named = [d for d, name in entries if name and sidecar_basename(name) == p.name]
    if not named:
        if len(entries) == 1 and entries[0][1] is None:
            # A bare digest with no filename: nothing to disagree with.
            named = [entries[0][0]]
        else:
            recorded_names = ", ".join(sorted({n or "<unnamed>" for _, n in entries}))
            raise ResultsIntegrityError(
                f"checksum sidecar {sidecar} does not record an entry for {p.name}; "
                f"it names {recorded_names}. Regenerate it, or delete it to proceed "
                "without verification."
            )

    # A sidecar must never say two different things about one file. Several
    # selected entries carrying *different* digests means one of them is
    # describing some other artifact, and accepting the file because *any* of
    # them agrees turns the sidecar into an attestation about a file it does
    # not describe -- the exact false attestation the recorded-name match
    # above exists to prevent, reintroduced through the basename fallback (or
    # through a rehomed sidecar that ended up with two same-named lines).
    # Several entries agreeing on one digest is not ambiguous and still
    # verifies: `shasum` run twice, or a rehomed line beside its original,
    # says the same thing twice.
    distinct = {d.lower() for d in named}
    if len(distinct) > 1:
        listed = ", ".join(sorted(distinct))
        raise ResultsIntegrityError(
            f"checksum sidecar {sidecar} records {len(distinct)} different digests for "
            f"{p.name} ({listed}); it cannot say which one describes this file. "
            "Regenerate it, or delete it to proceed without verification."
        )

    # Case-insensitive: hex is hex. PowerShell's Get-FileHash and 7-Zip emit
    # uppercase, and rejecting those as a mismatch reads to an operator as
    # "this evidence file was tampered with" over nothing but letter case.
    if not any(d.lower() == digest for d in named):
        raise ResultsIntegrityError(
            f"checksum mismatch for {p}: sidecar records {named[0]}, file hashes to {digest}"
        )
    return digest, True


def sidecar_basename(name: str) -> str:
    """The bare filename from a sidecar's recorded name.

    Backslashes are normalized first: shasum under Git Bash or MSYS can record
    a Windows-style path, and PurePosixPath would treat the whole thing as one
    filename.
    """
    return PurePosixPath(name.replace("\\", "/")).name


def _parse_sidecar(text: str) -> list[tuple[str, str | None]]:
    """Parse shasum-format lines into ``(digest, filename or None)`` pairs.

    One entry per line, not a flat ``.split()`` over the whole file: a
    multi-file sidecar flattened that way puts the second file's digest where
    a filename belongs and compares the wrong pair.
    """
    entries: list[tuple[str, str | None]] = []
    for line in text.splitlines():
        parts = line.split(None, 1)
        if not parts:
            continue
        digest = parts[0]
        name = parts[1].strip() if len(parts) > 1 else None
        # shasum marks binary-mode entries with a leading '*' on the filename.
        if name:
            name = name.lstrip("*")
        entries.append((digest, name or None))
    return entries


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


def check_results_rows(path: str | Path) -> None:
    """Refuse a results file whose rows are structurally wrong.

    ``reporting.load_results`` normalizes a malformed ``markers`` value to an
    empty list, because it renders the HTML and PDF reports from inside Quarto
    notebook cells where raising is an unreadable traceback. That leniency is
    wrong for a traceability matrix: a row whose ``markers`` is a JSON null or
    a string reads as carrying no control tags, so the control it was tagged
    for is reported as a GAP that does not exist -- the matrix asserting the
    suite is missing a check it actually has. Refuse the input instead.
    """
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise ResultsIntegrityError(f"could not read results file {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ResultsIntegrityError(f"could not read results file {p}: not a JSON object")

    results = raw.get("results", [])
    if not isinstance(results, list):
        raise ResultsIntegrityError(f"{p} has results={type(results).__name__}; expected a list")
    for index, row in enumerate(results):
        if not isinstance(row, dict):
            raise ResultsIntegrityError(
                f"{p} results[{index}] is a {type(row).__name__}; expected an object"
            )
        markers = row.get("markers", [])
        if not isinstance(markers, list):
            nodeid = row.get("nodeid", f"results[{index}]")
            raise ResultsIntegrityError(
                f"{p}: {nodeid} has markers={markers!r} ({type(markers).__name__}); "
                "expected a list. Control tags cannot be read from this file, so the "
                "matrix would report gaps that may not exist."
            )


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
