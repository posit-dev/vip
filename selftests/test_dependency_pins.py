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

A fourth invariant guards CI/local parity rather than the published wheel: the
Dockerfile's ``mcr.microsoft.com/playwright/python`` base image tag must track
the exact-pinned ``playwright`` version, so a ``docker run`` of the image
exercises the same Playwright build as a local ``uv run vip``.

A fifth invariant guards a different pin that drifted the same way (issue
#731): ``ruff`` is pinned exactly once, as ``ruff==<version>`` in the ``dev``
extra (and ``uv.lock``). Neither CI's ``astral-sh/ruff-action`` steps nor
``.pre-commit-config.yaml`` may carry their own copy of that version --
``ci.yml`` must leave the action's ``version`` input unset so it resolves
the pin from ``pyproject.toml``, and pre-commit must run ``uv run --extra
dev ruff`` (a local hook) instead of the separately-versioned
``ruff-pre-commit`` mirror.
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import yaml
from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
LOCKFILE = REPO_ROOT / "uv.lock"
DOCKERFILE = REPO_ROOT / "Dockerfile"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"

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
    "anyio",
    # Report/Jupyter stack: moved from the [report] extra into base deps so a
    # bare install renders (issue #554), then trimmed to just the kernel
    # Quarto's execution engine actually needs -- no `jupyter`/`jupyterlab`
    # metapackages. Still capped at next major.
    "pyyaml",
    "jupyter-client",
    "ipykernel",
    "nbformat",
    "nbclient",
    "tornado",
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
        assert len(specs) == 1, (
            f"{name} must be exact-pinned with '==' (found '{reqs[name].specifier}')"
        )
        assert specs[0].operator == "==", (
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


# Optional-dependency groups that must also be capped at next major. The
# ``report`` group is now an empty back-compat alias -- its packages moved into
# base [project.dependencies] (issue #554), where CAPPED enforces their bounds.
CAPPED_OPTIONAL = {
    "report": set(),
    "load": {"click", "locust", "msgpack", "python-engineio", "python-socketio"},
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


def _pinned_playwright_version() -> str:
    reqs = _runtime_requirements()
    specs = list(reqs["playwright"].specifier)
    assert len(specs) == 1, (
        f"playwright must be exact-pinned with '==' (found '{reqs['playwright'].specifier}')"
    )
    assert specs[0].operator == "==", (
        f"playwright must be exact-pinned with '==' (found '{reqs['playwright'].specifier}')"
    )
    return specs[0].version


def _dockerfile_playwright_tag() -> str:
    text = DOCKERFILE.read_text()
    match = re.search(
        r"^FROM mcr\.microsoft\.com/playwright/python:v([0-9.]+)-\S+",
        text,
        re.MULTILINE,
    )
    assert match, "Dockerfile is missing a FROM mcr.microsoft.com/playwright/python:vX.Y.Z-... line"
    return match.group(1)


def test_dockerfile_playwright_base_image_matches_pinned_version():
    """Guards CI/local parity: the Dockerfile's Playwright base image must not
    drift from the exact-pinned ``playwright`` package version (issue: the
    Dockerfile fell two minor versions behind pyproject.toml's pin).
    """
    pinned = _pinned_playwright_version()
    tag_version = _dockerfile_playwright_tag()
    assert tag_version == pinned, (
        f"Dockerfile FROM tag pins Playwright v{tag_version}, but pyproject.toml "
        f"pins playwright=={pinned}; bump the Dockerfile's "
        "mcr.microsoft.com/playwright/python tag to match"
    )


def test_ci_ruff_action_has_no_version_override():
    """Guards issue #731: an explicit ``version:`` input on an
    ``astral-sh/ruff-action`` step overrides the version the action would
    otherwise resolve from ``pyproject.toml``'s ``dev`` extra, letting CI's
    ruff drift from the one Dependabot bumps.
    """
    offenders = []
    for workflow_path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        workflow = yaml.safe_load(workflow_path.read_text()) or {}
        for job_name, job in (workflow.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                uses = step.get("uses", "")
                if uses.startswith("astral-sh/ruff-action@") and "version" in (
                    step.get("with") or {}
                ):
                    offenders.append(f"{workflow_path.name}:{job_name}:{step.get('name', uses)}")
    assert not offenders, (
        f"astral-sh/ruff-action step(s) pin an explicit version: {offenders}; "
        "remove the 'version' input so the action resolves it from "
        "pyproject.toml's dev extra instead"
    )


def test_pre_commit_ruff_hook_is_local_not_pinned_mirror():
    """Guards issue #731: pre-commit must run the locked ``uv run --extra
    dev ruff`` rather than the separately-versioned ``ruff-pre-commit``
    mirror, so pre-commit and CI/``just lint`` always agree on which ruff
    they run.
    """
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text()) or {}
    repos = config.get("repos") or []
    repo_urls = [repo.get("repo", "") for repo in repos]
    assert not any("ruff-pre-commit" in url for url in repo_urls), (
        f"pre-commit config still references astral-sh/ruff-pre-commit ({repo_urls}); "
        "replace it with a `repo: local` hook running `uv run --extra dev ruff`"
    )
    local_hook_ids = {
        hook.get("id")
        for repo in repos
        if repo.get("repo") == "local"
        for hook in (repo.get("hooks") or [])
    }
    assert {"ruff", "ruff-format"} <= local_hook_ids, (
        "expected local pre-commit hooks named 'ruff' and 'ruff-format'; "
        f"found local hook ids {sorted(local_hook_ids)}"
    )
