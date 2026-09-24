"""Helpers shared by more than one ``vip`` subcommand."""

from __future__ import annotations

import warnings
from pathlib import Path


def _resolve_effective_ca_bundle(insecure: bool, ca_bundle: Path | None) -> Path | None:
    """Apply --insecure/--ca-bundle precedence: insecure wins, ca_bundle is dropped.

    Warns when both are set (mirrors curl's own precedence for -k combined with
    --cacert). Shared by every command that accepts both flags -- ``verify`` (via
    ``_generate_temp_config``), and ``cleanup``/``uninstall`` (via
    ``_load_cleanup_config``/``run_uninstall``) -- so the collision is handled
    identically everywhere instead of three independent copies drifting apart.

    The warning fires on the collision regardless of where each value came
    from. ``cleanup``/``uninstall`` call this *after* merging a CLI flag with
    the corresponding ``vip.toml`` [tls] value (CLI wins per-field), so the
    pair handed in here may be flag+flag, toml+toml, or one of each -- the
    message therefore doesn't claim a CLI-only cause. This is a deliberate
    divergence from ``verify``: its own ``--config``/default-``./vip.toml``
    path loads ``[tls]`` straight through ``vip.config.load_config()`` and
    never calls this helper at all, so an identical ``vip.toml`` with both
    keys set warns for ``cleanup``/``uninstall`` but not for ``verify`` against
    that same file. Covered by ``test_toml_only_conflict_warns_and_insecure_wins``
    in ``selftests/test_cli_cleanup.py`` and its uninstall counterpart.
    """
    if insecure and ca_bundle:
        # stacklevel=2 attributes the warning to this helper's direct caller
        # (_generate_temp_config / _load_cleanup_config / run_uninstall).
        # Before this logic was extracted, the inline warnings.warn() in
        # _generate_temp_config used stacklevel=2 to reach *its* caller
        # instead -- one frame further up. No single stacklevel is correct
        # for all three call sites (they sit at different depths from the
        # command dispatch that ultimately triggered this), so this is a
        # deliberate, accepted drift rather than an oversight.
        warnings.warn(
            "insecure and a ca_bundle are both configured (whether via "
            "--insecure/--ca-bundle or [tls] insecure/ca_bundle in vip.toml); "
            "insecure takes precedence and the ca_bundle will be ignored for "
            "TLS verification.",
            stacklevel=2,
        )
    return None if insecure else ca_bundle
