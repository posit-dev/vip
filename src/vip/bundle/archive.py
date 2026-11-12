"""Collect the allowlisted report files, scan them for secrets, and write the zip."""

from __future__ import annotations

import html
import json
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, quote_plus

from vip.bundle.stamp import read_render_stamp, results_digest
from vip.errors import BundleError

# Read from the directory of results.json. results.json must exist.
REPORT_SIDECAR_FILES = ("results.json", "failures.json", "junit.xml", "results.sarif")
# Read from <report_dir>/_output/. _quarto.yml sets embed-resources, so each
# page is one self-contained file and no site_libs/ directory is needed.
RENDERED_FILES = ("index.html", "details.html", "vip-report.pdf")
# Files that hold credentials. --results must never name one of them.
FORBIDDEN_NAMES = frozenset(
    {"vip.toml", ".vip-auth-cache.json", ".vip-auth-cache.meta.json", ".vip-install.json"}
)

# A value shorter than this matches almost any file, so the scan skips it.
MIN_SECRET_LENGTH = 4
# Report text can hold only a part of a secret. failures.json and the error
# parser cut long text, which keeps the start. pytest shortens a long repr in
# the middle, which keeps the start and the end. So for each secret that is
# at least PARTIAL_MIN_SECRET_LENGTH long, the scan also looks for its first
# and its last PARTIAL_LENGTH characters, in each encoded form. A part with
# no digit or no letter, such as "password" or "20261105", matches normal
# report text, so the scan skips it. Random keys almost always have both. The
# start of every JWT, "eyJhbGci", has no digit, so the scan uses only the end
# of a JWT.
PARTIAL_LENGTH = 8
PARTIAL_MIN_SECRET_LENGTH = 16


@dataclass
class Collected:
    """The report files for the bundle by archive name, and what was left out.

    *sources* maps each archive name to the file on disk. *left_out* holds
    ``{"name": ..., "reason": ...}`` for each file that exists but is not in
    the bundle. *missing* holds the allowlisted files that do not exist.
    """

    members: dict[str, bytes] = field(default_factory=dict)
    sources: dict[str, Path] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    left_out: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _is_regular_file_in(path: Path, root: Path) -> bool:
    """Return True if *path* is a regular file in *root*, and neither is a link."""
    return (
        not path.is_symlink()
        and not path.parent.is_symlink()
        and path.is_file()
        and path.resolve().is_relative_to(root.resolve())
    )


def _read(path: Path) -> bytes:
    """Read *path*. Turn a read error into BundleError."""
    try:
        return path.read_bytes()
    except OSError as exc:
        raise BundleError(f"could not read {path}: {exc}") from exc


def _leave_out(out: Collected, archive_name: str, path: Path, reason: str, hint: str) -> None:
    out.left_out.append({"name": archive_name, "reason": reason})
    out.warnings.append(f"{path} is not in the bundle, because it {reason}.{hint}")


def _check_results_file(results_path: Path) -> bytes:
    """Return the bytes of *results_path*. Refuse a file that is not a VIP results file."""
    if results_path.name in FORBIDDEN_NAMES:
        raise BundleError(f"{results_path} is not a results file. Pass the results.json path.")
    if results_path.is_symlink() or results_path.parent.is_symlink():
        raise BundleError(f"{results_path} is a link. Pass the real path with --results PATH.")
    if not results_path.is_file():
        raise BundleError(
            f"no results found at {results_path}. Run 'vip verify' first, or pass --results PATH."
        )
    data = _read(results_path)
    try:
        parsed = json.loads(data)
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("results"), list):
        raise BundleError(
            f"{results_path} is not a VIP results file. Pass the results.json that "
            "'vip verify' wrote."
        )
    return data


def _generated_at(data: bytes) -> str | None:
    """Return the ``generated_at`` value of a results.json or a failures.json."""
    try:
        parsed = json.loads(data)
    except (ValueError, RecursionError):
        return None
    value = parsed.get("generated_at") if isinstance(parsed, dict) else None
    return value if isinstance(value, str) and value else None


def collect_members(results_path: Path, report_dir: Path) -> Collected:
    """Read the allowlisted report files.

    Sidecar files come from the directory of *results_path*. ``vip verify``
    writes the ``generated_at`` value of results.json to each sidecar. A
    failures.json with a different value is from a different run and is left
    out. A junit.xml or results.sarif that holds the value is from the same
    run. Any other sidecar is left out if it is older than results.json.
    Rendered files come from ``<report_dir>/_output/``. A rendered file is
    included only if the render stamp names it and the SHA-256 of this
    results.json. The secret scan cannot read the text in the PDF, so the PDF
    is safe only when its source, results.json, is in the bundle and passes
    the scan.
    """
    out = Collected()
    data = _check_results_file(results_path)
    out.members["report/results.json"] = data
    out.sources["report/results.json"] = results_path
    results_mtime = results_path.stat().st_mtime
    results_run = _generated_at(data)

    sidecar_dir = results_path.parent
    for name in REPORT_SIDECAR_FILES[1:]:
        path, archive_name = sidecar_dir / name, f"report/{name}"
        if not path.exists() and not path.is_symlink():
            out.missing.append(archive_name)
        elif not _is_regular_file_in(path, sidecar_dir):
            _leave_out(out, archive_name, path, "is a link or is not a regular file", "")
        else:
            content = _read(path)
            sidecar_run = _generated_at(content) if name == "failures.json" else None
            if results_run is not None and sidecar_run is not None:
                if sidecar_run != results_run:
                    reason = "is from a different run than results.json"
                    _leave_out(out, archive_name, path, reason, "")
                    continue
            elif results_run is not None and results_run.encode() in content:
                pass
            elif path.stat().st_mtime < results_mtime:
                hint = (
                    " If you copied the report directory without file times, "
                    "run 'vip verify' again."
                )
                _leave_out(out, archive_name, path, "is older than results.json", hint)
                continue
            out.members[archive_name] = content
            out.sources[archive_name] = path

    output_dir = report_dir / "_output"
    stamp = read_render_stamp(output_dir)
    digest = results_digest(data)
    hint = " Run 'vip report' again to include it."
    for name in RENDERED_FILES:
        path, archive_name = output_dir / name, f"report/_output/{name}"
        if not path.exists() and not path.is_symlink():
            out.missing.append(archive_name)
        elif not _is_regular_file_in(path, output_dir):
            _leave_out(out, archive_name, path, "is a link or is not a regular file", "")
        elif stamp is None or stamp[0] != digest or name not in stamp[1]:
            _leave_out(out, archive_name, path, f"was not made from {results_path}", hint)
        else:
            out.members[archive_name] = _read(path)
            out.sources[archive_name] = path
    if not any(name.startswith("report/_output/") for name in out.members):
        out.warnings.append("the bundle has no rendered report. Run 'vip report' to include it.")
    return out


def _encode(value: str) -> set[str]:
    """Return *value* in each form in which a report file can hold it.

    results.json and failures.json use json.dumps with ensure_ascii. The HTML
    pages escape markup characters. junit.xml escapes ``&`` and ``<`` in a
    text node but keeps ``"``. URLs are percent-encoded. Error text formats
    values with ``!r``, which doubles each backslash.
    """
    forms = {
        value,
        json.dumps(value)[1:-1],
        json.dumps(value, ensure_ascii=False)[1:-1],
        html.escape(value),
        html.escape(value, quote=False),
        quote(value, safe=""),
        quote_plus(value, safe=""),
    }
    as_repr = repr(value)[1:-1]
    forms |= {as_repr, json.dumps(as_repr)[1:-1]}
    return forms


def _is_compound(value: str) -> bool:
    """Return True for a whole URL or connection string.

    Its start is a scheme or a key such as ``Driver=``, which matches normal
    text. Its credential parts are separate secrets with their own partial forms.
    """
    return "://" in value or (";" in value and "=" in value)


def _is_distinct(part: str) -> bool:
    """Return True if *part* has a digit and a letter, so it is unlikely in normal text."""
    return any(c.isdigit() for c in part) and any(c.isalpha() for c in part)


def _encoded_forms(value: str) -> set[bytes]:
    """Return the byte forms of *value* and of its start and end, for the scan."""
    forms = _encode(value)
    if len(value) >= PARTIAL_MIN_SECRET_LENGTH and not _is_compound(value):
        for part in (value[:PARTIAL_LENGTH], value[-PARTIAL_LENGTH:]):
            if _is_distinct(part):
                forms |= _encode(part)
    return {form.encode("utf-8") for form in forms}


def _flatten(data: bytes) -> bytes:
    """Remove line breaks, raw or JSON-escaped, so that a wrapped secret is whole again."""
    for line_break in (b"\\r", b"\\n", b"\r", b"\n"):
        data = data.replace(line_break, b"")
    return data


def find_secret_hits(
    members: dict[str, bytes], secrets: Sequence[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Return sorted ``(member, label)`` pairs for each member that holds a secret.

    Each member is also checked with its line breaks removed, because a
    console log can wrap a long key across lines. Values shorter than
    MIN_SECRET_LENGTH are not checked. See :func:`short_secret_labels`.
    """
    patterns = [
        (label, _encoded_forms(value))
        for label, value in secrets
        if len(value) >= MIN_SECRET_LENGTH
    ]
    hits: set[tuple[str, str]] = set()
    for name, data in members.items():
        flat = _flatten(data)
        for label, forms in patterns:
            if any(form in data or form in flat for form in forms):
                hits.add((name, label))
    return sorted(hits)


def short_secret_labels(secrets: Sequence[tuple[str, str]]) -> list[str]:
    """Return the labels of the secrets that are too short for the scan."""
    return sorted({label for label, value in secrets if 0 < len(value) < MIN_SECRET_LENGTH})


def write_zip(output: Path, members: dict[str, bytes]) -> None:
    """Write *members* to *output* through a temp file in the same directory.

    The temp file replaces *output* only after every member is written. On
    any error the temp file is deleted, so a failed run leaves no partial zip.
    """
    with tempfile.NamedTemporaryFile(
        dir=output.parent, prefix=".vip-bundle-", suffix=".tmp", delete=False
    ) as handle:
        tmp = Path(handle.name)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name in sorted(members):
                zf.writestr(name, members[name])
        tmp.replace(output)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
