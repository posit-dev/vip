"""Regression tests for extension-directory fixture visibility (issue #609).

pytest scopes ``conftest.py`` fixtures by directory ancestry.  Before this fix,
VIP's core fixtures (``vip_config``, ``connect_client``, etc.) and BDD step
definitions lived only in ``src/vip_tests/conftest.py``, so a test collected
from a directory outside ``src/vip_tests`` -- exactly what ``--vip-extensions``
(or ``extension_dirs`` in vip.toml) adds to the collection -- could never see
them, even though ``pytest_sessionstart`` (``src/vip/plugin.py``) makes such a
directory *collectible*.  Requesting ``vip_config`` from an extension test
failed with ``fixture 'vip_config' not found``.

The fix moves the fixtures and step definitions into ``src/vip/fixtures.py``,
registered as part of VIP's pytest plugin in ``pytest_configure`` -- so they
are visible in any pytest session where ``vip`` is installed, independent of
directory ancestry.  These tests use ``pytester`` against the real installed
``vip`` package (entry-point plugin), not an in-repo fixture, so they exercise
the same mechanism a real extension author would hit.
"""

from __future__ import annotations

import pytest


class TestExtensionFixtureVisibility:
    @pytest.fixture()
    def ext_pytester(self, pytester):
        """pytester with a minimal vip.toml and no other collection targets."""
        pytester.makefile(".toml", vip='[general]\ndeployment_name = "Selftest"')
        return pytester

    def test_extension_directory_sees_vip_config(self, ext_pytester):
        """A plain test outside vip_tests/, loaded via --vip-extensions, can
        request vip_config.

        A plain (non-BDD) probe module is used deliberately: importing a
        pytest-bdd step module from a selftest is unsafe (``@scenario``
        inspects the caller's frame at import time), and VIP's own reporting
        hook collapses failure tracebacks into ``UnknownError: ...``, so a
        plain assertion keeps the failure message readable if this regresses.
        """
        ext_dir = ext_pytester.mkdir("my_extension")
        (ext_dir / "test_probe.py").write_text(
            "def test_needs_vip_config(vip_config):\n"
            "    assert vip_config.deployment_name == 'Selftest'\n"
        )
        result = ext_pytester.runpytest_subprocess(
            "--vip-config=vip.toml", f"--vip-extensions={ext_dir}", "-p", "no:randomly", "-v"
        )
        result.assert_outcomes(passed=1)

    def test_extension_directory_sees_given_steps(self, ext_pytester):
        """A pytest-bdd extension test can use VIP's shared "Given" steps.

        The three product-configuration guard steps (``connect_configured``,
        ``workbench_configured``, ``package_manager_configured``) are
        pytest-bdd step definitions, which pytest-bdd implements as fixtures --
        so they are subject to the exact same directory-ancestry scoping bug
        as ordinary fixtures.
        """
        # Package Manager must be configured, or VIP's own deselection logic
        # (pytest_collection_modifyitems -> _should_deselect_for_product)
        # drops the scenario before ever touching the "Given" step -- which
        # would make this test pass regardless of whether the step's fixture
        # actually resolves. Configuring it forces the step to run.
        ext_pytester.makefile(
            ".toml",
            vip='[general]\ndeployment_name = "Selftest"\n'
            '[package_manager]\nurl = "https://pm.example.com"\n',
        )
        ext_dir = ext_pytester.mkdir("my_bdd_extension")
        (ext_dir / "test_probe.feature").write_text(
            "Feature: probe\n"
            "  Scenario: package manager guard resolves\n"
            "    Given Package Manager is configured in vip.toml\n"
        )
        (ext_dir / "test_probe.py").write_text(
            "from pytest_bdd import scenario\n\n"
            '@scenario("test_probe.feature", "package manager guard resolves")\n'
            "def test_probe():\n"
            "    pass\n"
        )
        result = ext_pytester.runpytest_subprocess(
            "--vip-config=vip.toml", f"--vip-extensions={ext_dir}", "-p", "no:randomly", "-v"
        )
        # If the step's fixture can't resolve, this errors with "fixture
        # 'package_manager_configured' not found" instead of passing.
        result.assert_outcomes(passed=1)

    def test_extension_directory_sees_vip_config_under_xdist(self, ext_pytester):
        """The plugin (and its fixtures) registers per-worker, not just on the
        controller. ``vip.fixtures.register`` runs from ``pytest_configure``,
        which xdist workers execute independently as they bootstrap -- each is
        a fresh pytest process -- so this must pass identically to the
        non-distributed case above.
        """
        ext_dir = ext_pytester.mkdir("my_xdist_extension")
        (ext_dir / "test_probe.py").write_text(
            "def test_needs_vip_config(vip_config):\n"
            "    assert vip_config.deployment_name == 'Selftest'\n"
        )
        result = ext_pytester.runpytest_subprocess(
            "--vip-config=vip.toml",
            f"--vip-extensions={ext_dir}",
            "-p",
            "no:randomly",
            "-n",
            "2",
            "-v",
        )
        result.assert_outcomes(passed=1)

    def test_extension_directory_gets_vips_browser_launch_args_override(
        self, ext_pytester, monkeypatch
    ):
        """VIP's browser_type_launch_args override -- not pytest-playwright's
        stock fixture -- must win for a test collected outside vip_tests too.

        ``vip.fixtures.browser_type_launch_args`` and ``browser_context_args``
        override pytest-playwright's fixtures of the same name to inject VIP's
        proxy/TLS/storage-state config. Inside ``src/vip_tests``, a conftest.py
        fixture would always outrank a plugin fixture regardless of
        registration order -- but these two now live *only* in the globally
        registered "vip-fixtures" plugin (see the module docstring in
        ``vip/fixtures.py``), so for an extension directory the outcome
        depends on plugin-vs-plugin registration order against
        pytest-playwright's own plugin. ``vip.fixtures.register`` runs from
        ``pytest_configure``, which fires after every entry-point plugin
        (including pytest-playwright) has already registered -- so VIP's
        fixture should always be the last one registered, and therefore win.

        This asserts on a side effect pytest-playwright's stock fixture could
        never produce (an injected proxy dict), not merely that the fixture
        name resolves -- resolving is not enough to prove *which*
        implementation ran.
        """
        monkeypatch.setenv("HTTPS_PROXY", "http://gw.example:3128")
        ext_dir = ext_pytester.mkdir("my_proxy_extension")
        (ext_dir / "test_probe.py").write_text(
            "def test_launch_args_carry_vips_proxy(browser_type_launch_args):\n"
            "    proxy = browser_type_launch_args.get('proxy')\n"
            "    assert proxy is not None, (\n"
            "        'pytest-playwright fixture won -- VIP override did not apply: '\n"
            "        + repr(browser_type_launch_args)\n"
            "    )\n"
            "    assert proxy['server'] == 'http://gw.example:3128'\n"
        )
        result = ext_pytester.runpytest_subprocess(
            "--vip-config=vip.toml",
            f"--vip-extensions={ext_dir}",
            "-p",
            "no:randomly",
            "-v",
        )
        result.assert_outcomes(passed=1)

    def test_extension_directory_gets_vips_browser_context_args_override(self, ext_pytester):
        """Same override contract for browser_context_args (the fixture's
        other half): --vip-insecure must reach ignore_https_errors for a test
        collected outside vip_tests too."""
        ext_pytester.makefile(
            ".toml",
            vip='[general]\ndeployment_name = "Selftest"\n[tls]\ninsecure = true\n',
        )
        ext_dir = ext_pytester.mkdir("my_insecure_extension")
        (ext_dir / "test_probe.py").write_text(
            "def test_context_args_carry_insecure(browser_context_args):\n"
            "    assert browser_context_args.get('ignore_https_errors') is True, (\n"
            "        'pytest-playwright fixture won -- VIP override did not apply: '\n"
            "        + repr(browser_context_args)\n"
            "    )\n"
        )
        result = ext_pytester.runpytest_subprocess(
            "--vip-config=vip.toml", f"--vip-extensions={ext_dir}", "-p", "no:randomly", "-v"
        )
        result.assert_outcomes(passed=1)
