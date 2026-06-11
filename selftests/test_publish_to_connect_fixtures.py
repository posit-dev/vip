"""Selftests for the promoted Connect content-cleanup fixtures.

Verifies that ``_connect_created_guids``, ``_connect_content_cleanup``, and
``_connect_end_of_run_sweep`` are defined in the root
``src/vip_tests/conftest.py`` (and therefore visible to all test packages)
and are no longer duplicated in ``src/vip_tests/connect/conftest.py``.

Also verifies the ``python_shiny_bundle_path`` fixture produces a directory
with the expected files.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Paths to the conftest files under test
_ROOT_CONFTEST = (
    Path(__file__).parent.parent / "src" / "vip_tests" / "conftest.py"
)
_CONNECT_CONFTEST = (
    Path(__file__).parent.parent / "src" / "vip_tests" / "connect" / "conftest.py"
)
_WORKBENCH_CONFTEST = (
    Path(__file__).parent.parent / "src" / "vip_tests" / "workbench" / "conftest.py"
)

_CLEANUP_FIXTURES = (
    "_connect_created_guids",
    "_connect_content_cleanup",
    "_connect_end_of_run_sweep",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fixture_names_in(source: str) -> set[str]:
    """Return the names of all @pytest.fixture-decorated functions in *source*."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            # Matches @pytest.fixture, @pytest.fixture(...), and bare @fixture
            if isinstance(dec, ast.Attribute) and dec.attr == "fixture":
                names.add(node.name)
                break
            if isinstance(dec, ast.Call):
                func = dec.func
                if isinstance(func, ast.Attribute) and func.attr == "fixture":
                    names.add(node.name)
                    break
                if isinstance(func, ast.Name) and func.id == "fixture":
                    names.add(node.name)
                    break
            if isinstance(dec, ast.Name) and dec.id == "fixture":
                names.add(node.name)
                break
    return names


# ---------------------------------------------------------------------------
# Tests — fixture location
# ---------------------------------------------------------------------------


class TestCleanupFixturesPromotedToRoot:
    def test_root_conftest_defines_all_cleanup_fixtures(self):
        """All three cleanup fixtures must be in the root conftest."""
        source = _ROOT_CONFTEST.read_text()
        names = _fixture_names_in(source)
        for name in _CLEANUP_FIXTURES:
            assert name in names, (
                f"Expected fixture {name!r} to be defined in root conftest "
                f"({_ROOT_CONFTEST}), but it was not found."
            )

    def test_connect_conftest_does_not_duplicate_cleanup_fixtures(self):
        """The connect conftest must NOT re-define the promoted fixtures."""
        source = _CONNECT_CONFTEST.read_text()
        names = _fixture_names_in(source)
        for name in _CLEANUP_FIXTURES:
            assert name not in names, (
                f"Fixture {name!r} was found in connect conftest "
                f"({_CONNECT_CONFTEST}). It should only be in the root conftest."
            )

    def test_connect_conftest_retains_make_tar_gz(self):
        """_make_tar_gz must stay in connect conftest (other tests import it directly)."""
        source = _CONNECT_CONFTEST.read_text()
        assert "_make_tar_gz" in source, (
            f"_make_tar_gz helper disappeared from {_CONNECT_CONFTEST}. "
            "test_content_deploy.py and test_packages.py import it directly."
        )


# ---------------------------------------------------------------------------
# Tests — python_shiny_bundle_path fixture
# ---------------------------------------------------------------------------


class TestPythonShinyBundlePath:
    def test_fixture_defined_in_workbench_conftest(self):
        """python_shiny_bundle_path fixture must be in workbench conftest."""
        source = _WORKBENCH_CONFTEST.read_text()
        names = _fixture_names_in(source)
        assert "python_shiny_bundle_path" in names, (
            f"Expected fixture 'python_shiny_bundle_path' in {_WORKBENCH_CONFTEST}"
        )

    def test_bundle_creates_app_py(self, tmp_path_factory):
        """The fixture must create app.py in the returned directory."""
        from vip_tests.workbench.conftest import python_shiny_bundle_path

        # Manually invoke the fixture (it's session-scoped; we call it directly here).
        bundle_dir = python_shiny_bundle_path(tmp_path_factory)
        app_py = bundle_dir / "app.py"
        assert app_py.exists(), f"app.py not found in bundle directory {bundle_dir}"

    def test_bundle_creates_requirements_txt(self, tmp_path_factory):
        """The fixture must create requirements.txt in the returned directory."""
        from vip_tests.workbench.conftest import python_shiny_bundle_path

        bundle_dir = python_shiny_bundle_path(tmp_path_factory)
        req_txt = bundle_dir / "requirements.txt"
        assert req_txt.exists(), f"requirements.txt not found in {bundle_dir}"
        assert "shiny" in req_txt.read_text()

    def test_app_py_is_valid_python(self, tmp_path_factory):
        """app.py must parse as valid Python."""
        from vip_tests.workbench.conftest import python_shiny_bundle_path

        bundle_dir = python_shiny_bundle_path(tmp_path_factory)
        source = (bundle_dir / "app.py").read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"app.py contains invalid Python: {exc}") from exc

    def test_app_py_contains_shiny_app(self, tmp_path_factory):
        """app.py must define a Shiny App object."""
        from vip_tests.workbench.conftest import python_shiny_bundle_path

        bundle_dir = python_shiny_bundle_path(tmp_path_factory)
        source = (bundle_dir / "app.py").read_text()
        assert "App(" in source, "app.py must contain a Shiny App(...) call"
        assert "app_ui" in source, "app.py must define app_ui"


# ---------------------------------------------------------------------------
# Tests — root conftest autouse fixture order-of-operations
# ---------------------------------------------------------------------------


def test_cleanup_fixtures_are_autouse():
    """_connect_content_cleanup and _connect_end_of_run_sweep must be autouse."""
    source = _ROOT_CONFTEST.read_text()
    # Check for autouse=True in the fixture decorators
    tree = ast.parse(source)
    autouse_fixtures: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            is_fixture_call = (
                isinstance(func, ast.Attribute) and func.attr == "fixture"
            ) or (isinstance(func, ast.Name) and func.id == "fixture")
            if not is_fixture_call:
                continue
            for kw in dec.keywords:
                if kw.arg == "autouse" and isinstance(kw.value, ast.Constant):
                    if kw.value.value is True:
                        autouse_fixtures.add(node.name)

    assert "_connect_content_cleanup" in autouse_fixtures, (
        "_connect_content_cleanup must be autouse=True"
    )
    assert "_connect_end_of_run_sweep" in autouse_fixtures, (
        "_connect_end_of_run_sweep must be autouse=True"
    )


def test_end_of_run_sweep_is_session_scoped():
    """_connect_end_of_run_sweep must be scope='session'."""
    source = _ROOT_CONFTEST.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_connect_end_of_run_sweep":
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not (isinstance(func, ast.Attribute) and func.attr == "fixture"):
                continue
            for kw in dec.keywords:
                if kw.arg == "scope" and isinstance(kw.value, ast.Constant):
                    assert kw.value.value == "session", (
                        "_connect_end_of_run_sweep must have scope='session'"
                    )
                    return
    raise AssertionError(
        "_connect_end_of_run_sweep fixture not found with a scope keyword argument"
    )
