"""Guards VIP's published dependency-pinning policy (issue #399).

The wheel published to PyPI carries whatever version constraints live in
``pyproject.toml``'s ``[project.dependencies]``. To keep ``uv tool install
posit-vip`` / ``pip install posit-vip`` producing predictable output, the
dependencies that shape a ``vip`` run (pytest and its plugins, playwright) are
pinned to an exact version, and every other runtime dependency is capped below
its next major.

Two invariants are enforced so the policy cannot silently erode:

1. Each package in ``EXACT_PINS`` is pinned with ``==`` and that pin matches the
   version resolved in ``uv.lock`` (so the published pin is always the tested
   one).
2. Each package in ``CAPPED`` carries an upper bound so a breaking major release
   cannot slip in on a fresh install.
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
