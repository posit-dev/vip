"""Record which results.json each rendered report file was made from.

``vip report`` writes the stamp after each render. ``vip bundle`` reads it and
includes a rendered file only if the stamp names that file and the SHA-256 of
the results.json in the bundle. File times cannot do this, because a copy with
``shutil.copy2`` keeps the old time of the source file.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

STAMP_NAME = ".vip-render.json"


def results_digest(data: bytes) -> str:
    """Return the SHA-256 hex digest of the bytes of a results.json file."""
    return hashlib.sha256(data).hexdigest()


def clear_render_stamp(output_dir: Path) -> None:
    """Delete the stamp, so that a failed render leaves no stamp for old files."""
    (output_dir / STAMP_NAME).unlink(missing_ok=True)


def read_render_stamp(output_dir: Path) -> tuple[str, frozenset[str]] | None:
    """Return the digest and the rendered file names in the stamp, or None.

    A stamp that is missing, is a link, or does not parse gives None.
    """
    path = output_dir / STAMP_NAME
    if path.is_symlink():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    digest = data.get("results_sha256")
    files = data.get("files")
    if not isinstance(digest, str) or not isinstance(files, list):
        return None
    return digest, frozenset(name for name in files if isinstance(name, str))


def record_rendered(output_dir: Path, digest: str, names: Iterable[str]) -> None:
    """Add *names* to the stamp for *digest*. A stamp for another digest is replaced."""
    current = read_render_stamp(output_dir)
    files = set(names)
    if current is not None and current[0] == digest:
        files |= current[1]
    path = output_dir / STAMP_NAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"results_sha256": digest, "files": sorted(files)}, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
