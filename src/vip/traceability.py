"""Traceability matrix: join compliance controls against tagged test results.

VIP stays regulation-agnostic. The control list is supplied by whoever owns the
regulatory mapping; nothing here interprets ``reference``, ``risk`` or
``responsibility`` beyond carrying them through to the output.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

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
