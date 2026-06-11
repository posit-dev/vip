"""Fixtures for the cross-product GxP validation example.

All VIP core fixtures (vip_config, connect_client, workbench_client,
expected_r_versions, expected_python_versions, page, etc.) are available
automatically via the VIP plugin.

This conftest adds only the fixtures unique to this example:
  - check_packages   -- set to False to skip slow install-verification scenarios
  - r_package_name   -- the R package to verify (default: DESeq2)
  - python_package_name -- the Python package to verify (default: PyDeSEQ2)

Note: expected_r_versions and expected_python_versions are intentionally NOT
redefined here. They are already provided by VIP's core conftest
(src/vip_tests/conftest.py) and are wired to vip.toml [runtimes]. Redefining
them here would silently shadow the config-driven versions.

To populate these fixtures with real data, add a [runtimes] block to vip.toml:

    [runtimes]
    r_versions = ["4.4.0", "4.3.1"]
    python_versions = ["3.11.0", "3.10.0"]
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def check_packages() -> bool:
    """Control whether package install scenarios are executed.

    Set to False to skip the slow DESeq2/PyDeSEQ2 install checks when you
    only need runtime-version verification. Override in your own conftest.py:

        @pytest.fixture(scope="session")
        def check_packages() -> bool:
            return False
    """
    return True


@pytest.fixture(scope="session")
def r_package_name() -> str:
    """The R package to verify is installable on Connect and Workbench.

    Defaults to DESeq2. Override in your own conftest.py to check a
    different package:

        @pytest.fixture(scope="session")
        def r_package_name() -> str:
            return "ggplot2"
    """
    return "DESeq2"


@pytest.fixture(scope="session")
def python_package_name() -> str:
    """The Python package to verify is installable on Connect.

    Defaults to PyDeSEQ2. Override in your own conftest.py:

        @pytest.fixture(scope="session")
        def python_package_name() -> str:
            return "pandas"
    """
    return "PyDeSEQ2"
