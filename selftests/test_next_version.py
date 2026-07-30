"""Tests for scripts/next_version.py's calver release computation.

``scripts/`` is release machinery, not part of the installed package, so it
is never on the default import path. ``testpaths`` in ``pyproject.toml`` also
points at ``src/vip_tests``, not here -- both mean this module needs an
explicit ``sys.path`` insert to import ``next_version``.

The rule's failure modes are all annual or rarer (month reset, year
rollover, a skipped month), so it is covered by tests rather than by
observation.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from next_version import is_forward, next_version, parse_tag  # noqa: E402


class TestParseTag:
    def test_v_prefixed(self):
        assert parse_tag("v2026.7.13") == (2026, 7, 13)

    def test_bare(self):
        assert parse_tag("2026.7.13") == (2026, 7, 13)

    def test_legacy_semver(self):
        assert parse_tag("v0.58.12") == (0, 58, 12)

    def test_wrong_segment_count_rejected(self):
        with pytest.raises(ValueError):
            parse_tag("v2026.7")


class TestNextVersion:
    def test_same_month_patch_bump(self):
        assert next_version("v2026.7.0", date(2026, 7, 30)) == "2026.7.1"

    def test_new_month_resets_patch(self):
        assert next_version("v2026.7.3", date(2026, 8, 6)) == "2026.8.0"

    def test_december_to_january_rollover(self):
        assert next_version("v2026.12.2", date(2027, 1, 7)) == "2027.1.0"

    def test_skipped_month_still_resets(self):
        # Last release was July; August was skipped entirely.
        assert next_version("v2026.7.1", date(2026, 9, 3)) == "2026.9.0"

    def test_no_string_prefix_matching(self):
        # "2026.1." must never match as a prefix of "2026.10.0" -- tags are
        # parsed into integer tuples and compared numerically.
        assert next_version("v2026.10.0", date(2026, 1, 15)) == "2026.1.0"
        assert next_version("v2026.1.0", date(2026, 1, 15)) == "2026.1.1"

    def test_zero_x_cutover(self):
        assert next_version("v0.58.12", date(2026, 7, 30)) == "2026.7.0"

    def test_no_last_tag_starts_at_patch_zero(self):
        assert next_version(None, date(2026, 7, 30)) == "2026.7.0"


class TestIsForward:
    """The release workflow refuses any version that is not strictly newer."""

    def test_patch_bump_moves_forward(self):
        assert is_forward("2026.7.1", "v2026.7.0")

    def test_month_bump_moves_forward(self):
        assert is_forward("2026.8.0", "v2026.7.3")

    def test_calver_moves_forward_past_legacy_semver(self):
        assert is_forward("2026.7.0", "v0.58.17")

    def test_same_version_is_not_forward(self):
        assert not is_forward("2026.7.0", "v2026.7.0")

    def test_lower_version_is_not_forward(self):
        assert not is_forward("2026.7.0", "v2026.7.1")

    def test_future_month_tag_poisons_every_later_computed_version(self):
        # The reason is_forward is checked on the COMPUTED version too, not just
        # on an explicitly dispatched one. next_version keys off today's month,
        # so a tag in a future month (a mistaken dispatch, a hand-cut tag) makes
        # every run until the calendar catches up compute something lower than
        # the highest tag -- and each of those would be an unrecoverable
        # backwards publish to PyPI if it were allowed through.
        stray = "v2026.12.0"
        for today in (date(2026, 8, 6), date(2026, 9, 3), date(2026, 10, 1), date(2026, 11, 5)):
            computed = next_version(stray, today)
            assert not is_forward(computed, stray), (
                f"{computed} computed on {today} must be rejected against {stray}"
            )
