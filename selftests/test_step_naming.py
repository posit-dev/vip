"""Guard against pytest-bdd step functions being named ``test_*``.

A function decorated with ``@given``/``@when``/``@then`` is a step, not a test.
If it is *also* named ``test_*`` it matches pytest's default ``python_functions``
collection pattern, so pytest collects it as a standalone test in addition to
registering it as a step.

That stray test carries none of the feature file's ``@connect`` /
``@workbench`` / ``@package_manager`` markers (those are applied only to the
``@scenario``-decorated function), so the plugin's product deselection never
excludes it. It then runs against whatever product is configured and errors out
— e.g. a Connect data-source step running during a Package-Manager-only
``vip verify``. See the regression that prompted this guard.
"""

from __future__ import annotations

import ast
from pathlib import Path

_STEP_DECORATORS = {"given", "when", "then"}
_TESTS_ROOT = Path(__file__).resolve().parent.parent / "src" / "vip_tests"


def _decorator_name(node: ast.expr) -> str | None:
    """Return the bare callable name for a decorator like ``@when(...)`` or ``@when``."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):  # e.g. pytest_bdd.when(...)
        return node.attr
    return None


def _mis_named_steps(path: Path) -> list[str]:
    """Return names of step-decorated functions in *path* that start with ``test_``."""
    tree = ast.parse(path.read_text(), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("test_"):
            continue
        decorators = {_decorator_name(d) for d in node.decorator_list}
        if decorators & _STEP_DECORATORS:
            offenders.append(node.name)
    return offenders


def test_no_step_function_is_named_test() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _TESTS_ROOT.rglob("*.py"):
        names = _mis_named_steps(path)
        if names:
            offenders[str(path.relative_to(_TESTS_ROOT))] = names
    assert not offenders, (
        "pytest-bdd step functions must not be named test_* (pytest collects them "
        f"as stray, unmarked tests): {offenders}"
    )
