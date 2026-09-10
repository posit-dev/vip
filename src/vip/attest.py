"""Declaring what a skip *means*.

A validation tool has two very different reasons to not run a check, and
reporting them identically is how a green run comes to prove nothing:

``not_applicable``
    There was nothing to do. The product is not configured, the tier lacks
    the feature, the IDE is not installed. Skipping is the correct outcome
    and the run is still fully verified.

``unproven``
    VIP was asked to do something and could not. Authentication never
    completed, a prerequisite fixture failed, the environment lacked
    something the check needs. Nothing failed, but nothing was verified
    either, and the operator needs to know that.

Only the second affects the exit code. Use ``unproven`` whenever the skip
means a configured capability went unverified; use ``not_applicable`` when
the skip is a deliberate statement that the capability is out of scope for
this deployment.

The classification travels from the skip site to the report as a sentinel
prefix on the skip reason. That is deliberate: the reason string is the one
piece of a skip that pytest carries intact across process boundaries, so
this works from a fixture, from a step definition, and under xdist, none of
which reliably have access to the item stash. ``plugin._classify_skip_reason``
strips the sentinel again before anything human-facing sees it.
"""

from __future__ import annotations

from typing import NoReturn

import pytest

#: Internal transport marker. Prefixed to a skip's reason to classify it, and
#: stripped by ``plugin._classify_skip_reason`` before the reason is shown or
#: written to a report. Not part of the public interface -- call ``unproven``
#: rather than building the string yourself.
UNPROVEN_SENTINEL = "\x00vip:unproven\x00"


def unproven(reason: str) -> NoReturn:
    """Skip the current check, recording that it could not be verified.

    Use when VIP was asked to run this check and something prevented it.
    The result is reported as ``unproven`` rather than as an ordinary skip
    and, unless ``--allow-unproven`` is passed, fails the run.

    Args:
        reason: Why the check could not run, phrased for an operator reading
            the report. Name the cause, not the symptom.
    """
    pytest.skip(f"{UNPROVEN_SENTINEL}{reason}")


def not_applicable(reason: str) -> NoReturn:
    """Skip the current check because there is nothing here to verify.

    Use when skipping is the correct, final answer for this deployment --
    the product is not configured, or the feature does not apply. The run
    is still considered fully verified.

    Args:
        reason: Why the check does not apply to this deployment.
    """
    pytest.skip(reason)
