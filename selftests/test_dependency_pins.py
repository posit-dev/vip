"""Guards VIP's published dependency-pinning policy (issue #399).

The wheel published to PyPI carries whatever version constraints live in
``pyproject.toml``'s ``[project.dependencies]``. To keep ``uv tool install
posit-vip`` / ``pip install posit-vip`` producing predictable output, the
dependencies that shape a ``vip`` run (pytest and its plugins, playwright) are
pinned to an exact version, and every other runtime dependency is capped below
its next major.

Three invariants are enforced so the policy cannot silently erode:

1. Each package in ``EXACT_PINS`` is pinned with ``==`` and that pin matches the
   version resolved in ``uv.lock`` (so the published pin is always the tested
   one).
2. Each runtime dependency carries an upper bound, and every declared runtime
   dependency is classified as either ``EXACT_PINS`` or ``CAPPED`` (a new,
   unclassified dependency fails the suite rather than shipping uncapped).
3. Each ``report``/``load`` optional-group dependency carries an upper bound,
   and every declared entry in those groups is listed in ``CAPPED_OPTIONAL``.
"""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
LOCKFILE = REPO_ROOT / "uv.lock"

# Dependencies whose exact version determines a `vip` run's behaviour/output.
EXACT_PINS = {
    "playwright",
    "pytest",
    "pytest-bdd",
    "pytest-order",
    "pytest-playwright",
    "pytest-xdist",
}

# Runtime dependencies that must carry an upper bound (cap at next major). An
# upper bound is any of `<`, `<=`, `~=`, or `==`.
CAPPED = {
    "filelock",
    "httpx",
    "requests",
    "pygments",
    "mako",
    "idna",
    "pip",
    "tomli",
    "pyotp",
}

_BOUNDING_OPERATORS = {"<", "<=", "~=", "=="}


def canonical(name: str) -> str:
    return name.lower().replace("_", "-")


def _runtime_requirements() -> dict[str, Requirement]:
    data = tomllib.loads(PYPROJECT.read_text())
    return {
        canonical(Requirement(spec).name): Requirement(spec)
        for spec in data["project"]["dependencies"]
    }


def _locked_versions() -> dict[str, str]:
    data = tomllib.loads(LOCKFILE.read_text())
    return {canonical(pkg["name"]): pkg["version"] for pkg in data["package"]}


def test_output_drivers_are_exact_pinned_to_locked_version():
    reqs = _runtime_requirements()
    locked = _locked_versions()
    for name in sorted(EXACT_PINS):
        assert name in reqs, f"{name} missing from [project.dependencies]"
        specs = list(reqs[name].specifier)
        assert len(specs) == 1 and specs[0].operator == "==", (
            f"{name} must be exact-pinned with '==' (found '{reqs[name].specifier}')"
        )
        pinned = specs[0].version
        assert locked.get(name) == pinned, (
            f"{name}=={pinned} disagrees with uv.lock ({locked.get(name)}); "
            "re-pin to the locked version or run `just relock`"
        )


def test_other_runtime_deps_are_capped():
    reqs = _runtime_requirements()
    for name in sorted(CAPPED):
        assert name in reqs, f"{name} missing from [project.dependencies]"
        operators = {s.operator for s in reqs[name].specifier}
        assert operators & _BOUNDING_OPERATORS, (
            f"{name} must carry an upper bound (found '{reqs[name].specifier}')"
        )


def test_every_runtime_dependency_is_classified():
    """No runtime dep may escape the policy by not being listed above."""
    declared = set(_runtime_requirements())
    assert declared == EXACT_PINS | CAPPED, (
        "every [project.dependencies] entry must be listed in EXACT_PINS or "
        f"CAPPED; unclassified: {sorted(declared - (EXACT_PINS | CAPPED))}, "
        f"stale: {sorted((EXACT_PINS | CAPPED) - declared)}"
    )


# Optional-dependency groups that must also be capped at next major.
CAPPED_OPTIONAL = {
    "report": {
        "jinja2",
        "jupyter",
        "ipykernel",
        "nbformat",
        "nbclient",
        "nbconvert",
        "mistune",
        "tornado",
        "bleach",
        "jupyterlab",
    },
    "load": {"locust", "msgpack", "python-engineio", "python-socketio"},
}


def _optional_requirements(group: str) -> dict[str, Requirement]:
    data = tomllib.loads(PYPROJECT.read_text())
    return {
        canonical(Requirement(spec).name): Requirement(spec)
        for spec in data["project"]["optional-dependencies"][group]
    }


def test_report_and_load_groups_are_capped():
    for group, names in CAPPED_OPTIONAL.items():
        reqs = _optional_requirements(group)
        declared = set(reqs)
        assert declared == names, (
            f"every [{group}] entry must be listed in CAPPED_OPTIONAL[{group!r}]; "
            f"unclassified: {sorted(declared - names)}, stale: {sorted(names - declared)}"
        )
        for name in sorted(names):
            operators = {s.operator for s in reqs[name].specifier}
            assert operators & _BOUNDING_OPERATORS, (
                f"{name} in [{group}] must carry an upper bound (found '{reqs[name].specifier}')"
            )
