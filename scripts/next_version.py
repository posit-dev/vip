"""Compute the next calver release version from the last tag and today's date.

USAGE:
    uv run python scripts/next_version.py [--last-tag TAG] [--today YYYY-MM-DD]

VIP releases on a calendar-versioned, weekly train: the first release of a
calendar month is ``YYYY.M.0``; every later release that month bumps the
patch instead. See ``docs/development.md`` ("Versioning and the release
cadence") for the full rationale. Called by ``.github/workflows/release.yml``
to compute the version for a scheduled or dispatched release.
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import date, datetime, timezone


def parse_tag(tag: str) -> tuple[int, int, int]:
    """Parse a ``vYYYY.M.PATCH`` (or bare ``YYYY.M.PATCH``) tag into an int triple.

    Tags are always parsed into integers and compared as tuples, never as
    strings -- a string-prefix comparison would wrongly match ``"2026.1."``
    against ``2026.10.0``.
    """
    version = tag.removeprefix("v")
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"tag {tag!r} is not a MAJOR.MINOR.PATCH version")
    major, minor, patch = (int(p) for p in parts)
    return (major, minor, patch)


def next_version(last_tag: str | None, today: date) -> str:
    """Compute the next release version for ``today`` given the last release tag.

    The first release of a calendar month is ``YYYY.M.0``. A release already
    cut this calendar month bumps the patch instead of resetting. ``last_tag``
    of ``None`` (no prior release) also takes the reset branch, same as a
    last tag from an earlier month -- this is what makes the ``0.x`` cutover
    fall out of the ordinary rule with no special case: ``0.58.12`` parses to
    year-month ``(0, 58)``, which can never equal the current year-month.
    """
    year, month = today.year, today.month
    last = parse_tag(last_tag) if last_tag is not None else None
    patch = last[2] + 1 if last is not None and last[:2] == (year, month) else 0
    return f"{year}.{month}.{patch}"


def _highest_tag() -> str | None:
    """Return the highest version tag in this checkout, or None if there is none.

    Parses every ``v*`` tag with :func:`parse_tag` and takes the max by
    integer tuple, rather than trusting git's own tag sort or the most
    recently created tag -- "last tag" means highest version, not most recent
    by commit date.
    """
    result = subprocess.run(
        ["git", "tag", "--list", "v*"],
        capture_output=True,
        text=True,
        check=True,
    )
    parsed = []
    for line in result.stdout.splitlines():
        tag = line.strip()
        if not tag:
            continue
        try:
            parsed.append((parse_tag(tag), tag))
        except ValueError:
            continue
    if not parsed:
        return None
    return max(parsed, key=lambda pair: pair[0])[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute the next calver VIP release version")
    parser.add_argument(
        "--last-tag",
        help="Last release tag, e.g. v0.58.13. Defaults to the highest v* tag in this checkout.",
    )
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        help="Date to compute the release for (YYYY-MM-DD). Defaults to today (UTC).",
    )
    args = parser.parse_args()

    last_tag = args.last_tag if args.last_tag is not None else _highest_tag()
    today = args.today if args.today is not None else datetime.now(timezone.utc).date()
    print(next_version(last_tag, today))


if __name__ == "__main__":
    main()
