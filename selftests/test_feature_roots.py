"""_feature_roots resolves relative pytest args the way pytest itself does.

These go through a stub Config rather than `pytester`, which always runs with
cwd == rootdir and therefore cannot exercise the case these tests exist for:
pytest invoked from a subdirectory, where `invocation_params.dir` and
`rootpath` differ.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from vip.plugin import _discover_control_tags, _feature_roots

FEATURE = """@connect @control-audit-trail
Feature: F
  Scenario: S
    Given a thing
"""


def _config(args, rootpath, invocation_dir, ext_dirs=(), norecursedirs=None):
    """A stub with just the attributes _feature_roots and _discover_control_tags read."""
    stash: dict = {}
    if ext_dirs:
        from vip.plugin import _ext_dirs_key

        stash[_ext_dirs_key] = list(ext_dirs)
    return types.SimpleNamespace(
        args=list(args),
        rootpath=Path(rootpath),
        invocation_params=types.SimpleNamespace(dir=Path(invocation_dir)),
        stash=stash,
        getini=lambda name: norecursedirs if norecursedirs is not None else [],
    )


def test_relative_arg_resolves_against_the_invocation_dir(tmp_path):
    """The regression: resolving against rootpath yields a path that does not exist."""
    root = tmp_path / "repo"
    target = root / "src" / "tests"
    target.mkdir(parents=True)
    subdir = root / "selftests"
    subdir.mkdir()

    cfg = _config(args=["../src/tests"], rootpath=root, invocation_dir=subdir)
    roots = _feature_roots(cfg)

    assert [r.resolve() for r in roots] == [target.resolve()]
    assert roots[0].exists()


def test_control_tags_are_found_when_invoked_from_a_subdirectory(tmp_path):
    root = tmp_path / "repo"
    target = root / "src" / "tests"
    target.mkdir(parents=True)
    (target / "t.feature").write_text(FEATURE, encoding="utf-8")
    subdir = root / "selftests"
    subdir.mkdir()

    cfg = _config(args=["../src/tests"], rootpath=root, invocation_dir=subdir)
    assert _discover_control_tags(cfg) == {"control-audit-trail"}


def test_absolute_args_are_unaffected(tmp_path):
    target = tmp_path / "tests"
    target.mkdir()
    cfg = _config(args=[str(target)], rootpath=tmp_path, invocation_dir=tmp_path / "elsewhere")
    assert [r.resolve() for r in _feature_roots(cfg)] == [target.resolve()]


def test_nodeid_args_keep_only_the_path(tmp_path):
    target = tmp_path / "tests"
    target.mkdir()
    cfg = _config(
        args=[f"{target}::TestClass::test_thing"], rootpath=tmp_path, invocation_dir=tmp_path
    )
    assert [r.resolve() for r in _feature_roots(cfg)] == [target.resolve()]


def test_duplicate_roots_are_collapsed(tmp_path):
    """A targeted run passing many sibling paths must not rescan the same tree."""
    target = tmp_path / "tests"
    target.mkdir()
    cfg = _config(
        args=[str(target), str(target), f"{target}::x"], rootpath=tmp_path, invocation_dir=tmp_path
    )
    assert len(_feature_roots(cfg)) == 1


def test_no_args_falls_back_to_rootpath(tmp_path):
    cfg = _config(args=[], rootpath=tmp_path, invocation_dir=tmp_path / "elsewhere")
    assert [r.resolve() for r in _feature_roots(cfg)] == [tmp_path.resolve()]


def test_extension_dirs_are_scanned(tmp_path):
    ext = tmp_path / "ext"
    ext.mkdir()
    (ext / "t.feature").write_text(FEATURE, encoding="utf-8")
    cfg = _config(args=[], rootpath=tmp_path / "repo", invocation_dir=tmp_path, ext_dirs=[str(ext)])
    assert _discover_control_tags(cfg) == {"control-audit-trail"}


@pytest.mark.parametrize("ignored", [".venv", "node_modules"])
def test_norecursedirs_are_pruned(tmp_path, ignored):
    """A feature file inside an ignored directory must not register a marker."""
    buried = tmp_path / ignored / "pkg"
    buried.mkdir(parents=True)
    (buried / "t.feature").write_text(FEATURE, encoding="utf-8")

    cfg = _config(
        args=[str(tmp_path)],
        rootpath=tmp_path,
        invocation_dir=tmp_path,
        norecursedirs=[".*", "node_modules", "venv"],
    )
    assert _discover_control_tags(cfg) == set()

    unpruned = _config(args=[str(tmp_path)], rootpath=tmp_path, invocation_dir=tmp_path)
    assert _discover_control_tags(unpruned) == {"control-audit-trail"}


def test_norecursedirs_pattern_with_a_separator_matches_the_full_path(tmp_path):
    """pytest matches a pattern containing a separator against the whole path.

    Matching the basename only would scan a directory pytest itself would never
    collect, registering a control tag from a feature file that cannot run.
    """
    buried = tmp_path / "generated" / "pkg"
    buried.mkdir(parents=True)
    (buried / "t.feature").write_text(FEATURE, encoding="utf-8")

    cfg = _config(
        args=[str(tmp_path)],
        rootpath=tmp_path,
        invocation_dir=tmp_path,
        norecursedirs=[f"{tmp_path}/generated"],
    )
    assert _discover_control_tags(cfg) == set()


def test_a_bare_pattern_still_matches_by_basename(tmp_path):
    buried = tmp_path / "build" / "pkg"
    buried.mkdir(parents=True)
    (buried / "t.feature").write_text(FEATURE, encoding="utf-8")

    cfg = _config(
        args=[str(tmp_path)], rootpath=tmp_path, invocation_dir=tmp_path, norecursedirs=["build"]
    )
    assert _discover_control_tags(cfg) == set()


def test_a_non_matching_pattern_does_not_prune(tmp_path):
    kept = tmp_path / "generated" / "pkg"
    kept.mkdir(parents=True)
    (kept / "t.feature").write_text(FEATURE, encoding="utf-8")

    cfg = _config(
        args=[str(tmp_path)], rootpath=tmp_path, invocation_dir=tmp_path, norecursedirs=["build"]
    )
    assert _discover_control_tags(cfg) == {"control-audit-trail"}
