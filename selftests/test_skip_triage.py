"""Guards the skip-classification triage (#616).

A bare ``pytest.skip()`` still means "not applicable", which is the right
default for the sites nobody has looked at yet. But once a file *has* been
triaged, every skip in it should say which kind it is out loud -- otherwise
the next person to add a skip there silently reintroduces the ambiguity the
triage just removed, and the file quietly drifts back.

Add a file to ``TRIAGED_FILES`` when every skip in it has been deliberately
classified as ``attest.unproven`` or ``attest.not_applicable``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "vip_tests"

# Files whose every skip has been deliberately classified. Growing this list
# is the point; see #616.
TRIAGED_FILES = [
    "connect/test_content_deploy.py",
    "cross_product/test_ssl.py",
    "prerequisites/test_versions.py",
    "workbench/test_ide_launch.py",
    "workbench/test_jobs.py",
    "workbench/test_session_capacity.py",
    "workbench/test_session_capacity_k8s.py",
    "workbench/test_sessions.py",
]

# Tolerates whitespace anywhere the parser does, including a newline, so the
# guard cannot be evaded by reformatting. Scanned over the whole file rather
# than line by line for the same reason. ``\b`` before ``pytest`` keeps
# ``request.node.skip(...)`` and similar attribute calls out of it.
_BARE_SKIP = re.compile(r"\bpytest\s*\.\s*skip\s*\(")
_IMPORTS_ATTEST = re.compile(
    r"^\s*(?:from\s+vip\s+import\s+.*\battest\b|import\s+vip\.attest\b)", re.M
)


def find_bare_skips(text: str) -> list[int]:
    """Line numbers of every bare ``pytest.skip(`` call in *text*.

    A ``pytest.skip`` written inside a comment or docstring counts too. That
    is a deliberate false positive: it is loud and trivially reworded, whereas
    missing a real one is silent, and silence is the failure mode this whole
    guard exists to prevent.
    """
    return [text[: m.start()].count("\n") + 1 for m in _BARE_SKIP.finditer(text)]


def imports_attest(text: str) -> bool:
    """True when *text* really imports the helpers, not merely mentions them."""
    return _IMPORTS_ATTEST.search(text) is not None


@pytest.mark.parametrize("relpath", TRIAGED_FILES)
def test_triaged_file_has_no_unclassified_skip(relpath: str):
    path = _SRC / relpath
    assert path.exists(), f"{relpath} moved or was deleted; update TRIAGED_FILES"
    offenders = [f"{relpath}:{n}" for n in find_bare_skips(path.read_text())]
    assert not offenders, (
        "bare pytest.skip() in a triaged file -- say which kind of skip this is "
        "with attest.unproven() or attest.not_applicable():\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("relpath", TRIAGED_FILES)
def test_triaged_file_actually_uses_the_helpers(relpath: str):
    """Guards against 'triaging' a file by deleting its skips."""
    text = (_SRC / relpath).read_text()
    assert imports_attest(text), f"{relpath} is listed as triaged but never imports attest"


class TestBareSkipDetection:
    """The guard's own tests. A guard that is easy to evade is not a guard."""

    def test_finds_a_plain_call(self):
        assert find_bare_skips("x = 1\npytest.skip('no')\n") == [2]

    def test_finds_a_call_split_across_lines(self):
        # ruff would not format it this way, but a hand edit can, and a
        # line-by-line scan misses it entirely.
        assert find_bare_skips("pytest.\nskip('no')\n") == [1]

    def test_finds_a_call_with_whitespace_around_the_dot(self):
        assert find_bare_skips("pytest . skip ('no')\n") == [1]

    def test_ignores_the_attest_helpers(self):
        text = "attest.unproven('a')\nattest.not_applicable('b')\n"
        assert find_bare_skips(text) == []

    def test_ignores_an_unrelated_skip_attribute(self):
        assert find_bare_skips("request.node.skip('x')\nself.skip()\n") == []

    def test_reports_every_occurrence_in_order(self):
        text = "pytest.skip('a')\nx = 2\npytest.skip('b')\n"
        assert find_bare_skips(text) == [1, 3]


class TestAttestImportDetection:
    """ "attest" appearing anywhere is not evidence the file uses the helpers."""

    def test_accepts_the_real_import(self):
        assert imports_attest("from vip import attest\n")

    def test_accepts_a_module_import(self):
        assert imports_attest("import vip.attest\n")

    def test_rejects_a_mere_mention_in_a_comment(self):
        assert not imports_attest("# remember to use attest here\nimport pytest\n")

    def test_rejects_a_mention_in_a_docstring(self):
        assert not imports_attest('"""Uses attest for skips."""\nimport pytest\n')


def test_triage_list_has_no_duplicates():
    assert len(TRIAGED_FILES) == len(set(TRIAGED_FILES))
