"""Selftests for the promoted Connect content-cleanup fixtures.

Verifies that ``_connect_created_guids``, ``_connect_content_cleanup``, and
``_connect_end_of_run_sweep`` are defined in the root
``src/vip_tests/conftest.py`` (and therefore visible to all test packages)
and are no longer duplicated in ``src/vip_tests/connect/conftest.py``.

Also verifies the ``python_shiny_bundle_files`` fixture produces the expected
bundle contents (materialized server-side by the deploy step, not on disk).
"""

from __future__ import annotations

import ast
from pathlib import Path

# Imported at collection time, on purpose. ``test_content_deploy`` is a
# pytest-bdd module whose module-level ``@scenario`` decorators read
# ``pytest_bdd.utils.CONFIG_STACK[-1]``. pytest-bdd pushes the session config in
# a ``trylast`` ``pytest_configure`` but pops it unconditionally in
# ``pytest_unconfigure``, so an in-process ``pytester`` run (see
# ``selftests/test_plugin.py``) can pop the outer session's entry and leave the
# stack empty. Importing this module from inside a test body then raises
# ``IndexError: list index out of range`` whenever a pytester test happens to
# run earlier on the same xdist worker. Collection runs before any of that.
from vip_tests.connect import bundles, test_content_deploy

# Paths to the conftest files under test
_ROOT_CONFTEST = Path(__file__).parent.parent / "src" / "vip_tests" / "conftest.py"
_CONNECT_CONFTEST = Path(__file__).parent.parent / "src" / "vip_tests" / "connect" / "conftest.py"
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
# Tests — shared Shiny bundle (Connect + Workbench use the SAME bundle)
# ---------------------------------------------------------------------------

import json  # noqa: E402


class TestSharedShinyBundle:
    _R_VERSIONS = ["4.3.1", "4.6.0", "4.4.2"]

    def test_workbench_fixture_defined_in_conftest(self):
        """The Workbench shiny_bundle_spec fixture must exist in conftest."""
        source = _WORKBENCH_CONFTEST.read_text()
        names = _fixture_names_in(source)
        assert "shiny_bundle_spec" in names, (
            f"Expected fixture 'shiny_bundle_spec' in {_WORKBENCH_CONFTEST}"
        )

    def test_manifest_raw_url_points_at_public_repo_at_ref(self):
        """The manifest download URL must be the public raw URL pinned to a ref."""
        from vip_tests.connect.bundles import MANIFEST_REPO_PATH, manifest_raw_url

        url = manifest_raw_url("v9.9.9")
        assert url == (
            "https://raw.githubusercontent.com/posit-dev/vip/v9.9.9/" + MANIFEST_REPO_PATH
        )

    def test_manifest_url_ref_matches_installed_version(self):
        """The Workbench fixture pins the download to the installed VIP tag, so a
        released manifest always matches the app.R checksum shipped with it."""
        from vip import __version__
        from vip_tests.connect.bundles import manifest_raw_url

        assert manifest_raw_url(f"v{__version__}").endswith(
            f"/v{__version__}/src/vip_tests/connect/shiny_manifest.json"
        )

    def test_bundle_has_appR_and_manifest(self):
        """The shared builder returns an R app.R + manifest.json (not Python)."""
        from vip_tests.connect.bundles import build_shiny_bundle_files

        files = build_shiny_bundle_files(self._R_VERSIONS)
        assert set(files) == {"app.R", "manifest.json"}
        assert "shinyApp(" in files["app.R"]
        assert 'fluidPage("VIP test")' in files["app.R"]

    def test_manifest_is_shiny_appmode_with_newest_r(self):
        """Manifest platform is patched to the newest installed R; appmode=shiny."""
        from vip_tests.connect.bundles import build_shiny_bundle_files

        files = build_shiny_bundle_files(self._R_VERSIONS)
        manifest = json.loads(files["manifest.json"])
        assert manifest["metadata"]["appmode"] == "shiny"
        assert manifest["platform"] == "4.6.0"  # newest of _R_VERSIONS

    def test_manifest_checksum_matches_appR(self):
        """The manifest's app.R checksum must match the app.R bytes we ship,
        or ``rsconnect deploy manifest`` rejects the bundle."""
        import hashlib

        from vip_tests.connect.bundles import build_shiny_bundle_files

        files = build_shiny_bundle_files(self._R_VERSIONS)
        manifest = json.loads(files["manifest.json"])
        expected = manifest["files"]["app.R"]["checksum"]
        actual = hashlib.md5(files["app.R"].encode(), usedforsecurity=False).hexdigest()
        assert actual == expected, "app.R content drifted from its manifest checksum"

    def test_connect_and_workbench_use_identical_bundle(self):
        """The Connect deploy test and Workbench publish test must ship the
        byte-identical bundle -- both route through build_shiny_bundle_files."""

        # Connect's _get_bundle for the shiny item delegates to the shared builder.
        class _FakeConnect:
            def r_versions(self):
                return TestSharedShinyBundle._R_VERSIONS

        connect_bundle = test_content_deploy._get_bundle("vip-shiny-test", _FakeConnect())
        shared_bundle = bundles.build_shiny_bundle_files(self._R_VERSIONS)
        assert connect_bundle == shared_bundle


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
            is_fixture_call = (isinstance(func, ast.Attribute) and func.attr == "fixture") or (
                isinstance(func, ast.Name) and func.id == "fixture"
            )
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
