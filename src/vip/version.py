"""Posit calendar-version parsing and comparison.

Posit Team products (Connect, Workbench, Package Manager) use a calendar
versioning scheme: ``YYYY.MM.patch``, optionally followed by a pre-release
suffix (``-dev``, ``-daily.<date>``, ``-preview``) and/or a build metadata
suffix (``+build``). Examples: ``2026.06.0``, ``2026.06.0-dev+123``,
``2026.06.0-daily.20260615``, ``2026.06.0-preview``.

This replaces the old ``plugin._version_tuple`` helper, which took the first
run of digits per dot-separated segment and ignored suffixes entirely --
fragile on real Posit version strings and unable to express "pre-release
sorts before release".
"""

from __future__ import annotations

import re
from functools import total_ordering

# Pre-release kinds, ordered from "earliest in the release cycle" to "latest
# before the final release". There's no upstream spec pinning this down, so
# the ordering here is a judgment call: a "dev" build is the least finished
# (arbitrary point during development), "daily" is a scheduled nightly build
# of `main` (further along, but still unstable), and "preview" is a
# release-candidate-like build cut shortly before the final release. All
# three sort before the plain (final) release of the same numeric version.
_PRERELEASE_ORDER = {"dev": 0, "daily": 1, "preview": 2}

# Final release has no suffix; it must sort after every pre-release kind.
_FINAL_RANK = len(_PRERELEASE_ORDER)

_VERSION_RE = re.compile(
    r"""
    ^
    (?P<year>\d+)\.(?P<month>\d+)\.(?P<patch>\d+)
    (?:-(?P<pre_kind>dev|daily|preview)(?:[.-](?P<pre_extra>[0-9A-Za-z.-]+))?)?
    (?:\+(?P<build>[0-9A-Za-z.-]+))?
    $
    """,
    re.VERBOSE,
)


@total_ordering
class ProductVersion:
    """A parsed, comparable Posit calendar version.

    Comparison key is ``(year, month, patch, prerelease_rank, prerelease_extra)``.
    Build metadata (``+build``) does not affect ordering (matches semver
    convention: build metadata is informational only), but is preserved for
    display via ``__str__``/``__repr__``.

    Raises ``ValueError`` for any string that doesn't match the
    ``YYYY.MM.patch[-dev|-daily[.X]|-preview][+build]`` shape.
    """

    __slots__ = ("_raw", "year", "month", "patch", "pre_kind", "pre_extra", "build")

    def __init__(self, raw: str) -> None:
        match = _VERSION_RE.match(raw.strip())
        if not match:
            raise ValueError(
                f"Cannot parse {raw!r} as a Posit calendar version "
                "(expected YYYY.MM.patch[-dev|-daily|-preview][+build])"
            )
        self._raw = raw
        self.year = int(match.group("year"))
        self.month = int(match.group("month"))
        self.patch = int(match.group("patch"))
        self.pre_kind: str | None = match.group("pre_kind")
        self.pre_extra: str | None = match.group("pre_extra")
        self.build: str | None = match.group("build")

    @property
    def _prerelease_rank(self) -> int:
        """Sort rank among pre-release kinds; final releases rank highest."""
        if self.pre_kind is None:
            return _FINAL_RANK
        return _PRERELEASE_ORDER[self.pre_kind]

    def _sort_key(self) -> tuple[int, int, int, int, str]:
        return (
            self.year,
            self.month,
            self.patch,
            self._prerelease_rank,
            self.pre_extra or "",
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProductVersion):
            return NotImplemented
        return self._sort_key() == other._sort_key()

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ProductVersion):
            return NotImplemented
        return self._sort_key() < other._sort_key()

    def __hash__(self) -> int:
        return hash(self._sort_key())

    def __str__(self) -> str:
        return self._raw

    def __repr__(self) -> str:
        return f"ProductVersion({self._raw!r})"


# Posit Team product versions this release of VIP is built and validated
# against. This is a curated statement of intent -- what the release targets --
# not a mechanical floor derived from the ``@pytest.mark.min_version`` markers.
# Keep it in sync when the suite starts targeting a newer product release.
# Surfaced by ``vip --product-versions``.
TARGETED_PRODUCT_VERSIONS: dict[str, str] = {
    "connect": "2026.06.0",
}
