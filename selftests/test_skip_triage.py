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

_BARE_SKIP = re.compile(r"\bpytest\.skip\s*\(")


@pytest.mark.parametrize("relpath", TRIAGED_FILES)
def test_triaged_file_has_no_unclassified_skip(relpath: str):
    path = _SRC / relpath
    assert path.exists(), f"{relpath} moved or was deleted; update TRIAGED_FILES"
    offenders = [
        f"{relpath}:{n}"
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if _BARE_SKIP.search(line)
    ]
    assert not offenders, (
        "bare pytest.skip() in a triaged file -- say which kind of skip this is "
        "with attest.unproven() or attest.not_applicable():\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("relpath", TRIAGED_FILES)
def test_triaged_file_actually_uses_the_helpers(relpath: str):
    """Guards against 'triaging' a file by deleting its skips."""
    text = (_SRC / relpath).read_text()
    assert "attest" in text, f"{relpath} is listed as triaged but never imports attest"


def test_triage_list_has_no_duplicates():
    assert len(TRIAGED_FILES) == len(set(TRIAGED_FILES))
