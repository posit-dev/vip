"""Resource profile detection and capping for the Workbench capacity scenarios."""

from __future__ import annotations

import logging
import re
import warnings

from playwright.sync_api import Locator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Resource profile helpers
# Shared between test_session_capacity.py and test_session_capacity_k8s.py,
# both of which need to detect and skip resource profiles that Workbench
# renders as visible-but-disabled for the authenticated user.
# ---------------------------------------------------------------------------


class ResourceProfileDisabledError(Exception):
    """Raised when the target resource profile is present but disabled for the user.

    Workbench renders resource profiles the authenticated user is not entitled
    to (e.g. a group-restricted profile) as visible options with
    ``aria-disabled='true'`` / ``data-disabled``.  Clicking one just blocks
    until Playwright's timeout, so ``_launch_session`` raises this instead and
    lets the caller record the profile as unavailable and move on.
    """

    def __init__(self, profile: str) -> None:
        super().__init__(profile)
        self.profile = profile


def _option_is_disabled(option: Locator) -> bool:
    """Return True if a ``[role='option']`` is disabled for the current user.

    Radix-based selects mark unavailable options with ``aria-disabled='true'``
    and an (empty-valued) ``data-disabled`` attribute; ``get_attribute``
    returns ``""`` for the latter, so test for presence rather than truthiness.
    """
    return (
        option.get_attribute("aria-disabled") == "true"
        or option.get_attribute("data-disabled") is not None
    )


# Cap on how many auto-detected resource profiles the capacity scenarios launch
# at once (#631).  A deployment that *advertises* N profiles cannot necessarily
# run all N concurrently: the CI Workbench container offers Default, Small,
# Medium and Large, which together request 8 CPUs and 30 GB from a 4-vCPU
# runner, so launching every one measured the runner's limits rather than the
# deployment's.  An explicit ``workbench.session_profiles`` list is never
# capped -- that list is a deliberate statement about the deployment.
MAX_AUTO_DETECTED_PROFILES = 2

_PROFILE_CPU_RE = re.compile(r"(\d+(?:\.\d+)?)\s*v?CPUs?\b", re.IGNORECASE)
_PROFILE_MEM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(G|M)i?B\b", re.IGNORECASE)


def profile_size_key(name: str) -> tuple[float, float]:
    """Sort key approximating a resource profile's size from its dropdown label.

    Workbench renders each profile's allocation inline, e.g. ``Medium (2 CPUs,
    8GB RAM)``, so the label alone orders them smallest-first without asking
    the launcher.  A label carrying no parseable allocation sorts last: an
    unknown size is the one we least want to launch when capping.
    """
    cpu = _PROFILE_CPU_RE.search(name)
    mem = _PROFILE_MEM_RE.search(name)
    cpus = float(cpu.group(1)) if cpu else float("inf")
    if mem is None:
        return (cpus, float("inf"))
    # 1024, so these are mebibytes. The exact unit does not matter -- this is only
    # ever a sort key -- but the name should not claim otherwise.
    mebibytes = float(mem.group(1)) * (1024 if mem.group(2).upper() == "G" else 1)
    return (cpus, mebibytes)


def _quoted(names: list[str]) -> str:
    """Render *names* as a quoted, comma-separated list.

    Resource-profile labels embed their own commas, so an unquoted join produces
    an unparseable run-on list in the warning.
    """
    return ", ".join(repr(n) for n in names)


def cap_auto_detected_profiles(
    names: list[str], *, limit: int = MAX_AUTO_DETECTED_PROFILES
) -> list[str]:
    """Return at most *limit* of the auto-detected *names*, smallest first.

    Only for profiles discovered from the dropdown.  Launching every advertised
    profile at once exhausts a modest host, and a session that loses that
    contention fails the scenario for a reason that is not the deployment's
    capacity -- which is how the CI nightly came to fail on a different profile
    each run (#631).

    Capping is reported through both ``warnings.warn`` and the logger, matching
    :func:`oidc_login_lock`: VIP is a verification tool, so a run that
    exercised fewer profiles than the deployment offers must say so rather than
    report a narrower check as a full one.  ``limit`` of 0 or less disables the
    cap.
    """
    if limit <= 0 or len(names) <= limit:
        return list(names)
    ordered = sorted(names, key=profile_size_key)
    chosen, dropped = ordered[:limit], ordered[limit:]
    # Labels contain commas of their own ("Medium (2 CPUs, 8GB RAM)"), so a bare
    # ", " join reads as one run-on list. Quote each label to keep the boundaries
    # visible.
    message = (
        f"Auto-detected {len(names)} enabled resource profiles; launching only the "
        f"{limit} smallest ({_quoted(chosen)}) and skipping {_quoted(dropped)}. "
        "Launching every advertised profile at once exhausts a modest host and fails "
        "the scenario for a reason that is not the deployment's capacity. Set "
        "workbench.session_profiles in vip.toml to choose the profiles explicitly; "
        "an explicit list is never capped."
    )
    warnings.warn(message, stacklevel=2)
    logger.warning(message)
    return chosen
