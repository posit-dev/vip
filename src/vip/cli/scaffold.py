"""``vip scaffold``: copy an example extension template to a directory."""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

from vip.errors import (
    ConfigError,
    VipError,
)

# Registry of scaffold templates: name -> (examples/ source directory, one-line
# description). "cross-product" is the default so existing `vip scaffold
# --output DIR` invocations (predating --template) are unchanged.
_SCAFFOLD_TEMPLATES: dict[str, tuple[str, str]] = {
    "minimal": (
        "custom_tests",
        "Single-scenario HTTP health check against your configured product (start here)",
    ),
    "cross-product": (
        "cross_product_validation",
        "R/Python runtime versions and package installability across Connect and Workbench",
    ),
}
_DEFAULT_SCAFFOLD_TEMPLATE = "cross-product"


def _resolve_scaffold_source(dirname: str, stack: contextlib.ExitStack) -> Path | None:
    """Locate the source directory for a scaffold template, or None if missing.

    Prefer the bundled copy inside the installed wheel (_scaffold/ is embedded
    via [tool.hatch.build.targets.wheel.force-include]).  Fall back to the
    repo's top-level examples/ directory so in-repo usage and selftests work
    without building a wheel first.

    The bundled path is materialized through ``importlib.resources.as_file``,
    whose context must stay open for as long as anyone reads from the returned
    path: for a zip-imported package as_file() extracts into a temporary
    directory that is deleted when the context exits, so closing it here would
    hand back a path that no longer exists by the time the caller copies from
    it.  It is entered on the caller's ExitStack instead, which run_scaffold
    holds open across the copy -- the same pattern _ensure_report_templates
    uses for the bundled Quarto templates.
    """
    import importlib.resources

    try:
        scaffold_pkg = importlib.resources.files("vip") / "_scaffold" / dirname
        # files() returns a Traversable; we need a real Path for shutil.copytree.
        p = stack.enter_context(importlib.resources.as_file(scaffold_pkg))
        if p.is_dir():
            return p
    except (TypeError, OSError, ModuleNotFoundError):
        pass

    # Source checkout: four levels up from src/vip/cli/scaffold.py → repo root.
    repo_root = Path(__file__).parent.parent.parent.parent
    candidate = repo_root / "examples" / dirname
    if candidate.is_dir():
        return candidate
    return None


def _scaffold_next_steps(template: str, dest: Path) -> str:
    """Per-template "Next steps" text printed after a successful scaffold."""
    if template == "cross-product":
        return (
            f"\nNext steps:\n"
            f"  1. Edit {dest / 'conftest.py'} to set your package names and versions.\n"
            f"  2. Add a [runtimes] block to vip.toml:\n"
            f"       [runtimes]\n"
            f'       r_versions = ["4.4.0"]\n'
            f'       python_versions = ["3.11.0"]\n'
            f"  3. Run the extension:\n"
            f"       vip verify --config vip.toml --extensions {dest}\n"
            f"\nSee {dest / 'README.md'} for full customization instructions."
        )
    return (
        f"\nNext steps:\n"
        f"  1. Edit {dest / 'test_custom_check.feature'} and"
        f" {dest / 'test_custom_check.py'} to check your own endpoint.\n"
        f"  2. Run the extension:\n"
        f"       vip verify --config vip.toml --extensions {dest}\n"
        f"\nSee {dest / 'README.md'} for full customization instructions."
    )


def run_scaffold(args: argparse.Namespace) -> None:
    """Copy a scaffold template to a user-specified directory, or list templates."""
    import shutil

    if getattr(args, "list", False):
        print("Available templates:\n")
        for name, (_dirname, description) in _SCAFFOLD_TEMPLATES.items():
            print(f"  {name} - {description}")
        return

    template = getattr(args, "template", None) or _DEFAULT_SCAFFOLD_TEMPLATE
    if template not in _SCAFFOLD_TEMPLATES:
        valid = ", ".join(sorted(_SCAFFOLD_TEMPLATES))
        raise ConfigError(f"unknown template {template!r}. Valid templates: {valid}")
    dirname, _description = _SCAFFOLD_TEMPLATES[template]

    # One ExitStack spans every read of a bundled resource: the paths handed
    # back by _resolve_scaffold_source are only guaranteed to exist while it is
    # open (see that function's docstring).
    with contextlib.ExitStack() as stack:
        src = _resolve_scaffold_source(dirname, stack)
        if src is None:
            raise VipError(
                f"could not locate examples/{dirname}/. "
                "Ensure VIP is installed from source or as a wheel built with examples."
            )

        dest = Path(args.output)
        if dest.exists() and not args.force:
            raise ConfigError(f"destination already exists: {dest}\nPass --force to overwrite.")

        if dest.exists():
            if dest.is_dir() and not dest.is_symlink():
                shutil.rmtree(dest)
            else:
                dest.unlink()

        shutil.copytree(src, dest)

        # AGENTS.md is shared across every template (single source of truth), so
        # it's copied in separately rather than living inside each template dir.
        shared_agents_md = _resolve_scaffold_source("_shared", stack)
        if shared_agents_md is not None:
            shutil.copyfile(shared_agents_md / "AGENTS.md", dest / "AGENTS.md")
        else:
            # Don't fail the scaffold over it -- the tests themselves are still
            # usable -- but say so, because a silently missing AGENTS.md means a
            # packaging regression that is otherwise invisible to the user.
            print(
                "Warning: could not locate examples/_shared/AGENTS.md; "
                "the scaffolded directory has no extension-authoring guide.",
                file=sys.stderr,
            )

    print(f"Scaffolded extension to: {dest}")
    print(_scaffold_next_steps(template, dest))
