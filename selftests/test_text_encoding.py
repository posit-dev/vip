"""Guard against locale-dependent ``Path.read_text()`` / ``write_text()`` and subprocess calls.

Without ``encoding=``, Python decodes with the locale encoding, which is cp1252 on
Windows and fails on UTF-8 bytes such as 0x8d (issue #752: the R Markdown manifest
could not be read by ``test_deploy_rmarkdown``). Ruff's PLW1514 enforces this too,
but it only fires when it can infer the receiver is a ``pathlib.Path``, so it misses
``(Path(__file__).parent / "x.json").read_text()`` -- the exact shape of that bug.
This AST scan covers every ``read_text``/``write_text`` call regardless of receiver.

Subprocess calls with ``text=True`` (or ``universal_newlines=True``) and no ``encoding=``
decode the child's output with the same locale encoding, so they get the same scan.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCAN_DIRS = ("src", "selftests", "examples", "docker", "scripts")
_POSITIONAL_ARGS_BEFORE_ENCODING = {"read_text": 0, "write_text": 1}


def _missing_encoding(path: Path) -> list[str]:
    """Return ``file:line`` for read_text/write_text calls in *path* without an encoding."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        n_positional = _POSITIONAL_ARGS_BEFORE_ENCODING.get(node.func.attr)
        if n_positional is None:
            continue
        has_encoding = len(node.args) > n_positional or any(
            k.arg == "encoding" for k in node.keywords
        )
        if not has_encoding:
            offenders.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno}")
    return offenders


def _is_true(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _missing_subprocess_encoding(path: Path) -> list[str]:
    """Return ``file:line`` for calls in *path* that enable text mode without an encoding."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        keywords = {k.arg: k.value for k in node.keywords}
        text_mode = any(_is_true(keywords.get(name)) for name in ("text", "universal_newlines"))
        if text_mode and "encoding" not in keywords:
            offenders.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno}")
    return offenders


def _python_files() -> list[Path]:
    return sorted(
        p for d in _SCAN_DIRS if (_REPO_ROOT / d).is_dir() for p in (_REPO_ROOT / d).rglob("*.py")
    )


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.relative_to(_REPO_ROOT)))
def test_text_io_specifies_encoding(path: Path) -> None:
    assert _missing_encoding(path) == [], (
        "read_text()/write_text() without encoding= uses the locale encoding "
        '(cp1252 on Windows); pass encoding="utf-8"'
    )


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.relative_to(_REPO_ROOT)))
def test_subprocess_text_mode_specifies_encoding(path: Path) -> None:
    assert _missing_subprocess_encoding(path) == [], (
        "text=True without encoding= decodes child output with the locale encoding "
        '(cp1252 on Windows); pass encoding="utf-8", errors="replace"'
    )
