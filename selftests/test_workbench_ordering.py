"""Tests for the collection order of the Workbench BDD test suite.

Workbench tests currently collect in alphabetical file order, which interleaves
foundational tests (auth, session launch) with dependent ones (extensions,
git ops) in an order that has nothing to do with what actually needs to run
first. This asserts the *intentional* order imposed via ``pytest-order``
markers (epic #480 / issues #481, #482):

- Auth is the gate: it must collect before session launch.
- Session launch is foundational: it must collect before both the IDE
  extensions checks and Git operations, which depend on a launched session.
- IDE extensions is the last in-session feature to validate, so it must be
  the last Workbench file whose scenarios need a live session.
- Sign-out collects dead last, after everything: it ends the shared auth
  session every other scenario depends on, so nothing may follow it.

We only assert these invariants (not the full brittle sequence) so future
insertions between the documented rank gaps don't churn this test.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKBENCH_DIR = _REPO_ROOT / "src" / "vip_tests" / "workbench"

_NODEID_RE = re.compile(r"^\S+::\S+$")


def _slow_workbench_stems() -> set[str]:
    """Return the stems of Workbench feature files tagged ``@slow``.

    Derived from the files themselves (not hardcoded) so the deselection
    test below self-maintains as the ``@slow`` set changes. The intended
    membership is locked separately in ``test_gherkin.py``.
    """
    stems = {f.stem for f in _WORKBENCH_DIR.glob("*.feature") if "@slow" in f.read_text()}
    assert stems, "expected at least one @slow-tagged Workbench feature file"
    return stems


def _collect_workbench_nodeids(tmp_path: Path, marker_expr: str | None = None) -> list[str]:
    """Run ``pytest --collect-only`` over the Workbench suite and return node ids in order.

    Workbench and Connect must both be "configured" (a URL present) or every
    Workbench test gets deselected outright by the plugin's product-config
    gate (``_should_deselect_for_product``) -- ``test_publish_to_connect``
    requires both products, and an unconfigured product means "no test at
    all", not "collected but skipped".

    Pass *marker_expr* to add a ``-m`` filter (e.g. ``"not slow"``, what
    ``vip verify --basic`` applies) and observe which scenarios survive it.
    """
    config_path = tmp_path / "vip.toml"
    config_path.write_text(
        '[workbench]\nurl = "https://workbench.example.com"\n\n'
        '[connect]\nurl = "https://connect.example.com"\n'
    )

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(_WORKBENCH_DIR),
        "--collect-only",
        "-q",
        f"--vip-config={config_path}",
    ]
    if marker_expr is not None:
        cmd.extend(["-m", marker_expr])

    result = subprocess.run(
        cmd,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"collection failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    nodeids = [
        line.strip() for line in result.stdout.splitlines() if _NODEID_RE.match(line.strip())
    ]
    assert nodeids, f"no node ids parsed from collection output:\n{result.stdout}"
    return nodeids


def _file_of(nodeid: str) -> str:
    """Return the test file stem (e.g. ``test_auth``) for a collected node id."""
    return Path(nodeid.split("::", 1)[0]).stem


def _function_of(nodeid: str) -> str:
    """Return the test function name (e.g. ``test_launch_rstudio``) for a node id.

    Strips the trailing ``[chromium]`` parametrize suffix so callers can
    compare against the bare scenario function name.
    """
    return nodeid.split("::", 1)[1].split("[", 1)[0]


def _first_index_of_file(nodeids: list[str], file_stem: str) -> int:
    for i, nodeid in enumerate(nodeids):
        if _file_of(nodeid) == file_stem:
            return i
    raise AssertionError(f"{file_stem} did not collect any tests: {nodeids}")


def test_auth_collects_before_ide_launch(tmp_path: Path) -> None:
    nodeids = _collect_workbench_nodeids(tmp_path)
    auth_idx = _first_index_of_file(nodeids, "test_auth")
    launch_idx = _first_index_of_file(nodeids, "test_ide_launch")
    assert auth_idx < launch_idx, (
        f"test_auth (index {auth_idx}) must collect before test_ide_launch "
        f"(index {launch_idx}): {nodeids}"
    )


def test_ide_launch_collects_before_ide_extensions(tmp_path: Path) -> None:
    nodeids = _collect_workbench_nodeids(tmp_path)
    launch_idx = _first_index_of_file(nodeids, "test_ide_launch")
    extensions_idx = _first_index_of_file(nodeids, "test_ide_extensions")
    assert launch_idx < extensions_idx, (
        f"test_ide_launch (index {launch_idx}) must collect before "
        f"test_ide_extensions (index {extensions_idx}): {nodeids}"
    )


def test_ide_launch_collects_before_git_ops(tmp_path: Path) -> None:
    nodeids = _collect_workbench_nodeids(tmp_path)
    launch_idx = _first_index_of_file(nodeids, "test_ide_launch")
    git_ops_idx = _first_index_of_file(nodeids, "test_git_ops")
    assert launch_idx < git_ops_idx, (
        f"test_ide_launch (index {launch_idx}) must collect before "
        f"test_git_ops (index {git_ops_idx}): {nodeids}"
    )


def test_ide_extensions_is_the_last_in_session_workbench_file(tmp_path: Path) -> None:
    """Extensions stays last among scenarios that need a live session.

    Sign-out now collects after it (see
    :func:`test_signout_collects_dead_last`), so this asserts "last of the
    in-session files" rather than "last overall". Sign-out is not an in-session
    feature check -- it tears the session down.
    """
    nodeids = _collect_workbench_nodeids(tmp_path)
    in_session = [n for n in nodeids if not n.endswith("test_workbench_signout[chromium]")]
    last_file = _file_of(in_session[-1])
    assert last_file == "test_ide_extensions", (
        f"test_ide_extensions must be the last in-session Workbench test file collected, "
        f"got {last_file!r} last: {in_session}"
    )


def test_signout_collects_dead_last(tmp_path: Path) -> None:
    """Nothing may collect after sign-out.

    Under --interactive-auth / --headless-auth every Workbench scenario shares
    one account, so signing out ends the session the rest of them are using.
    Anything ordered after it inherits a signed-out browser.
    """
    nodeids = _collect_workbench_nodeids(tmp_path)
    assert nodeids[-1].endswith("test_workbench_signout[chromium]"), (
        f"test_workbench_signout must collect last, got {nodeids[-1]!r}: {nodeids}"
    )


def test_login_collects_before_signout(tmp_path: Path) -> None:
    """The login scenario keeps its own logged-out context and stays early."""
    nodeids = _collect_workbench_nodeids(tmp_path)
    login_idx = next(
        i for i, n in enumerate(nodeids) if n.endswith("test_workbench_login[chromium]")
    )
    signout_idx = next(
        i for i, n in enumerate(nodeids) if n.endswith("test_workbench_signout[chromium]")
    )
    assert login_idx < signout_idx, f"login must collect before sign-out: {nodeids}"


def test_ide_marker_selects_matching_launch_and_extensions_scenarios(tmp_path: Path) -> None:
    """#592: each IDE marker must select exactly its launch scenario plus its
    (if any) extensions scenario -- nothing else.

    ``pytest_collection_modifyitems`` in ``workbench/conftest.py`` groups
    Workbench items for xdist purely off this marker set (see
    ``_workbench_group_name``): every item carrying a given IDE marker lands
    in that IDE's ``workbench_ide_<ide>`` group. So an IDE marker selecting
    exactly the launch+extensions pair here is what "shares its IDE's group"
    reduces to -- if a scenario carried the wrong marker (or none), this
    would select the wrong set of files.

    RStudio has no extensions scenario today, so its marker selects only the
    launch file.

    Asserting scenario *function names* (not just file stems) matters: a
    marker mix-up between two IDEs on the extensions functions (e.g. jupyter
    and positron swapped between ``test_jupyterlab_extensions`` and
    ``test_positron_extensions``) would still select the right *file* --
    ``test_ide_extensions`` -- for both markers, and a file-only assertion
    would not catch it.
    """
    marker_to_expected_functions = {
        "rstudio": {"test_launch_rstudio"},
        "vscode": {"test_launch_vscode", "test_vscode_extensions"},
        "jupyter": {"test_launch_jupyter", "test_jupyterlab_extensions"},
        "positron": {"test_launch_positron", "test_positron_extensions"},
    }
    for marker, expected_functions in marker_to_expected_functions.items():
        nodeids = _collect_workbench_nodeids(tmp_path, marker_expr=marker)
        functions = {_function_of(n) for n in nodeids}
        assert functions == expected_functions, (
            f"-m {marker} should select exactly {expected_functions}, got {functions}: {nodeids}"
        )


def test_basic_marker_deselects_slow_workbench_features(tmp_path: Path) -> None:
    """End-to-end: ``-m "not slow"`` (what ``vip verify --basic`` applies) must
    drop exactly the @slow-tagged Workbench features and keep the basic ones.

    This exercises the full chain the other selftests only cover in isolation:
    real ``.feature`` files -> pytest-bdd Gherkin-tag->pytest-marker conversion
    -> ``-m`` deselection. It would catch a pytest-bdd change (or a stray
    ``pytest_bdd_apply_tag`` hook) that silently stopped converting ``@slow``,
    which would turn ``--basic`` into a no-op with no other failing test.
    """
    slow_files = _slow_workbench_stems()
    all_files = {_file_of(n) for n in _collect_workbench_nodeids(tmp_path)}
    basic_nodeids = _collect_workbench_nodeids(tmp_path, marker_expr="not slow")
    basic_files = {_file_of(n) for n in basic_nodeids}

    # Sanity: unfiltered, the @slow files really do collect (so a broken
    # collection can't let the deselection assertion pass vacuously).
    assert slow_files <= all_files, (
        f"expected all @slow files unfiltered; missing {slow_files - all_files}"
    )
    # The filter drops every @slow file ...
    leaked = slow_files & basic_files
    assert not leaked, f"@slow files leaked into a `not slow` run: {leaked}"
    # ... and keeps a known basic feature (Chronicle stays in the basic run).
    assert "test_chronicle" in basic_files, (
        f"test_chronicle should remain in a basic run: {sorted(basic_files)}"
    )
