"""Guard that .dockerignore keeps up with pyproject's forced includes.

``.dockerignore`` excludes ``examples/*`` wholesale and then re-includes, by
hand, the directories that ``[tool.hatch.build.targets.wheel.force-include]``
pulls into the wheel. Those two lists are separate files with no mechanical
link, so adding a scaffold template to pyproject.toml and forgetting the
negation here breaks every container build -- and it breaks it at ``uv sync``
inside Docker, with ``FileNotFoundError: Forced include not found``, which is a
long way from the change that caused it.

This is what happened when the ``minimal`` template and the shared
``AGENTS.md`` were added: selftests stayed green on every platform while the
rhel9/rhel10/opensuse install jobs and the Mock-IdP E2E job all failed.
"""

from __future__ import annotations

import sys
from pathlib import Path

# tomllib is stdlib from 3.11; VIP still supports 3.10, where tomli backfills
# it. Same guard as src/vip/config.py.
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_DOCKERIGNORE = _REPO_ROOT / ".dockerignore"


def _force_included_example_paths() -> set[str]:
    """examples/ paths that pyproject force-includes into the wheel."""
    data = tomllib.loads(_PYPROJECT.read_text())
    force_include = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    return {src for src in force_include if src.startswith("examples/")}


def _dockerignore_negations() -> set[str]:
    """Paths re-included via a leading ``!`` in .dockerignore."""
    return {
        line.strip().lstrip("!")
        for line in _DOCKERIGNORE.read_text().splitlines()
        if line.strip().startswith("!")
    }


def test_examples_are_force_included_somewhere():
    # Keeps the assertion below from passing vacuously if the pyproject
    # layout ever changes shape and the lookup silently yields nothing.
    assert _force_included_example_paths()


def test_every_force_included_example_is_reincluded_in_dockerignore():
    missing = _force_included_example_paths() - _dockerignore_negations()
    assert not missing, (
        "pyproject.toml force-includes these examples/ paths into the wheel but "
        f".dockerignore does not re-include them, so Docker builds will fail with "
        f"'Forced include not found': {sorted(missing)}"
    )
