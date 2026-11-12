"""Record which results.json each rendered report file was made from.

``vip report`` writes the stamp after each render. The stamp holds the SHA-256
of the results.json and the SHA-256 of each rendered file. ``vip bundle``
includes a rendered file only if both digests match. File times cannot do
this, because a copy with ``shutil.copy2`` keeps the old time of the source
file.
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


def file_digest(data: bytes) -> str:
    """Return the SHA-256 hex digest of the bytes of a rendered file."""
    return hashlib.sha256(data).hexdigest()


def read_render_stamp(output_dir: Path) -> tuple[str, dict[str, str]] | None:
    """Return the results digest and the digest of each rendered file, or None.

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
    if not isinstance(digest, str) or not isinstance(files, dict):
        return None
    return digest, {
        name: value
        for name, value in files.items()
        if isinstance(name, str) and isinstance(value, str)
    }


def record_rendered(output_dir: Path, digest: str, names: Iterable[str]) -> None:
    """Add the files *names* in *output_dir* to the stamp for *digest*.

    The stamp holds the SHA-256 of each file as it is now. A stamp for
    another digest is replaced.
    """
    current = read_render_stamp(output_dir)
    files = dict(current[1]) if current is not None and current[0] == digest else {}
    for name in names:
        files[name] = file_digest((output_dir / name).read_bytes())
    path = output_dir / STAMP_NAME
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"results_sha256": digest, "files": files}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
