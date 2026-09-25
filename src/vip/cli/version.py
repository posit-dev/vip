"""``vip version``: print the vip version and the Posit Team support floor."""

from __future__ import annotations

import argparse

from vip import __version__
from vip.version import MINIMUM_SUPPORTED_POSIT_TEAM


def _format_version_details() -> str:
    """Render the vip version and the minimum supported Posit Team release.

    VIP's own version and the Posit Team support floor are both calendar-versioned
    (e.g. ``2026.7.0``) but are unrelated numbers, so each line is labeled
    explicitly to avoid a reader mistaking one for the other.
    """
    return (
        f"VIP version: {__version__}\n"
        f"Supported Posit Team versions: {MINIMUM_SUPPORTED_POSIT_TEAM} and newer"
    )


def run_version(_args: argparse.Namespace) -> None:
    """Print the vip version and the minimum supported Posit Team version."""
    print(_format_version_details())
