"""Rot guard for examples/_shared/AGENTS.md.

AGENTS.md (copied into every ``vip scaffold`` output directory) enumerates the
public fixtures and registered markers an extension author may rely on. A
hand-maintained inventory that silently drifts from the real source is worse
than none, so this module parses the real source directly -- never a second
hardcoded list -- and asserts every name AGENTS.md claims still resolves.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_AGENTS_MD = _REPO_ROOT / "examples" / "_shared" / "AGENTS.md"
_CONFTEST = _REPO_ROOT / "src" / "vip_tests" / "conftest.py"
_PLUGIN = _REPO_ROOT / "src" / "vip" / "plugin.py"

# Matches a markdown table row's first cell when it's inline code, e.g.
# "| `connect_client` | ..." or "| `min_version(product, version)` | ...".
# Anchored to line start so it only ever matches the first column -- a type
# column later in the same row (also often inline code) never has a "|"
# immediately preceding it once the pattern is anchored this way.
_TABLE_FIRST_CELL_CODE = re.compile(r"^\|\s*`([a-zA-Z_][a-zA-Z0-9_]*)(?:\([^)]*\))?`", re.MULTILINE)


def _section(markdown: str, heading: str) -> str:
    """Return the text of a ``## heading`` section, up to the next ``## ``."""
    _, _, rest = markdown.partition(f"## {heading}")
    body, _, _ = rest.partition("\n## ")
    return body


def _agents_md_fixture_names() -> set[str]:
    section = _section(_AGENTS_MD.read_text(), "Public fixtures")
    return set(_TABLE_FIRST_CELL_CODE.findall(section))


def _agents_md_marker_names() -> set[str]:
    section = _section(_AGENTS_MD.read_text(), "Registered markers")
    return set(_TABLE_FIRST_CELL_CODE.findall(section))


def _real_fixture_names() -> set[str]:
    """Public (non-underscore) fixture names defined in VIP core's conftest.

    A function counts as a fixture when it carries a ``@pytest.fixture`` (or
    ``@pytest.fixture(...)``) decorator. Parsed via AST rather than a regex so
    decorator arguments (``scope="session"``, etc.) don't need to be modeled.
    """
    tree = ast.parse(_CONFTEST.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.name.startswith("_"):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(target, ast.Attribute) and target.attr == "fixture":
                names.add(node.name)
                break
    return names


def _real_marker_names() -> set[str]:
    """Marker names registered via ``config.addinivalue_line("markers", ...)``."""
    text = _PLUGIN.read_text()
    names: set[str] = set()
    for declaration in re.findall(r'addinivalue_line\(\s*"markers",\s*"([^"]+)"', text):
        name = re.split(r"[:(]", declaration, maxsplit=1)[0].strip()
        names.add(name)
    return names


def test_agents_md_documents_at_least_one_fixture_and_marker():
    # A guard against the extraction regexes themselves silently matching
    # nothing (e.g. after a heading rename) and the emptiness making the
    # "no missing names" assertions below vacuously true.
    assert _agents_md_fixture_names()
    assert _agents_md_marker_names()


def test_agents_md_fixtures_all_resolve_in_conftest():
    claimed = _agents_md_fixture_names()
    real = _real_fixture_names()
    missing = claimed - real
    assert not missing, (
        f"AGENTS.md documents fixtures that don't exist in "
        f"src/vip_tests/conftest.py: {sorted(missing)}"
    )


def test_agents_md_markers_all_resolve_in_plugin():
    claimed = _agents_md_marker_names()
    real = _real_marker_names()
    missing = claimed - real
    assert not missing, (
        f"AGENTS.md documents markers that don't exist in src/vip/plugin.py: {sorted(missing)}"
    )
