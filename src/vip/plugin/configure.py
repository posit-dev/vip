"""``pytest_configure`` and the other session-setup hooks: markers, warning filters,
config loading, xdist credential forwarding, and extension directories.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from vip.config import load_config
from vip.fixtures import register as _register_fixtures
from vip.plugin import state
from vip.plugin.auth import _configure_auth
from vip.plugin.terminal import _install_location_shortener, _install_progress_recolor
from vip.proxy import build_proxy_map
from vip.stash import (
    _auth_mode_key,
    _auth_session_key,
    _ext_dirs_key,
    _results_key,
    _session_start_key,
    _vip_config_key,
)


def pytest_configure(config: pytest.Config) -> None:
    """Load VIP's config, register its fixtures/markers/warning filters, and run browser auth.

    Stashes the parsed ``VIPConfig`` and merged extension directories on ``config.stash``
    for fixtures and collection hooks to read, and — outside xdist workers — performs
    the ``--interactive-auth``/``--headless-auth`` browser login, stashing the resulting
    session for ``pytest_sessionfinish`` to clean up.
    """
    state._active_config = config

    # Register VIP's core fixtures and shared BDD steps as their own pytest
    # plugin (see vip.fixtures' module docstring for why: directory-scoped
    # conftest.py fixtures are invisible to extension directories loaded via
    # --vip-extensions, issue #609). Runs once per pytest process, so xdist
    # workers register it too (each is a fresh process that goes through
    # pytest_configure independently).
    _register_fixtures(config)

    # Register the canonical warning filters in the plugin so they apply
    # regardless of the pytest rootdir, including when vip is installed into
    # an unrelated project.
    for line in (
        # gherkin-official 29.0.0 passes maxsplit positionally to re.split;
        # fixed upstream but pulled transitively via pytest-bdd.
        "ignore:'maxsplit' is passed as positional argument:DeprecationWarning:gherkin",
        # TLS downgrade tests deliberately use deprecated TLS 1.0/1.1 versions.
        "ignore:ssl.TLSVersion.TLSv1:DeprecationWarning",
        "ignore:ssl.TLSVersion.TLSv1_1:DeprecationWarning",
        # pytest-bdd scenario functions return fixture values; not a real issue.
        "ignore::pytest.PytestReturnNotNoneWarning",
        # pytest-bdd 8.1.0 injects fixtures via _register_fixture(nodeid=...) and
        # FixtureDef(baseid=...), which pytest >= 9.1 deprecates in favor of node=.
        # Framework-level and only fixable when pytest-bdd updates; nothing VIP can
        # change. A category filter is required because the warning surfaces from two
        # modules (pytest_bdd and _pytest.fixtures), so module/message scoping misses one.
        "ignore::pytest.PytestRemovedIn10Warning",
        # gevent monkey-patching happens after ssl is imported by other plugins;
        # unavoidable without patching at process start.
        "ignore:Monkey-patching ssl",
    ):
        config.addinivalue_line("filterwarnings", line)

    # Register markers
    config.addinivalue_line("markers", "connect: tests for Posit Connect")
    config.addinivalue_line("markers", "workbench: tests for Posit Workbench")
    config.addinivalue_line("markers", "package_manager: tests for Posit Package Manager")
    config.addinivalue_line("markers", "prerequisites: prerequisite checks")
    config.addinivalue_line("markers", "cross_product: cross-product / admin tests")
    config.addinivalue_line(
        "markers",
        "performance: performance validation tests (opt-in; excluded by default)",
    )
    config.addinivalue_line("markers", "security: security validation tests")
    config.addinivalue_line(
        "markers",
        "config_hygiene: checks of VIP's own configuration (opt-in; excluded by default)",
    )
    config.addinivalue_line(
        "markers",
        "slow: detailed/long-running checks; excluded by --basic",
    )
    config.addinivalue_line(
        "markers",
        "min_version(product, version): skip when product is below the specified version",
    )
    config.addinivalue_line(
        "markers",
        "if_applicable: skip when the related feature is not configured",
    )
    config.addinivalue_line(
        "markers",
        "api_auth: test requires only an API key, not browser credentials",
    )
    config.addinivalue_line("markers", "rstudio: Workbench RStudio IDE scenario")
    config.addinivalue_line("markers", "vscode: Workbench VS Code IDE scenario")
    config.addinivalue_line("markers", "jupyter: Workbench JupyterLab IDE scenario")
    config.addinivalue_line("markers", "positron: Workbench Positron IDE scenario")

    # In concise mode, suppress the "short test summary info" section — the
    # inline concise error messages make it redundant.
    if not config.getoption("--vip-verbose", default=False):
        config.option.reportchars = ""

    # Show skip/xfail reasons in full on the verbose (``-v``) test line instead
    # of ellipsizing them to the terminal width. pytest only prints the
    # untrimmed reason at *test-case* verbosity >= 2 (see _pytest/terminal.py).
    # Bumping that fine-grained level — rather than the global ``-v`` count —
    # leaves failure tracebacks and assertion reprs at the user's chosen
    # verbosity, and a skip reason never carries a traceback, so this only ever
    # lengthens a one-line reason. We act only when the user passed exactly
    # ``-v`` (resolved test-case verbosity 1): at level 0 the reporter is in
    # dot mode and bumping would force per-test lines on; above 1 it is already
    # full. An explicit ``verbosity_test_cases`` in the user's config (anything
    # other than the "auto" default) is respected.
    try:
        if (
            config.getini("verbosity_test_cases") == "auto"
            and config.get_verbosity(pytest.Config.VERBOSITY_TEST_CASES) == 1
        ):
            config._inicache["verbosity_test_cases"] = "2"
    except (ValueError, AttributeError):
        pass

    # Load VIP config and stash it for fixtures / collection hooks.
    vip_cfg = load_config(config.getoption("--vip-config"))
    config.stash[_vip_config_key] = vip_cfg

    # Initialize per-session results list (avoids module-level global).
    config.stash[_results_key] = []

    # Merge extension dirs from config file and CLI.
    ext_dirs: list[str] = list(vip_cfg.extension_dirs)
    ext_dirs.extend(config.getoption("--vip-extensions") or [])
    config.stash[_ext_dirs_key] = ext_dirs

    _any_product_configured = any(
        pc.is_configured for pc in (vip_cfg.connect, vip_cfg.workbench, vip_cfg.package_manager)
    )
    if _any_product_configured and not hasattr(config, "workerinput"):
        # Resolve the proxy map once on the controller, purely so that a promoted
        # lone HTTP_PROXY announces itself somewhere the user will actually see
        # it.  ``vip.proxy`` emits that notice wherever the promotion happens,
        # but every other entry point into it during a run is a client fixture
        # or a URL probe -- pytest captures their output and hides it on a
        # passing run, whereas output from ``pytest_configure`` is not captured.
        #
        # Workers are excluded for the same reason the auth branches below are:
        # pytest_configure fires on every one of them, and the notice would be
        # repeated once per worker.  Runs with no product configured are excluded
        # because this plugin loads from an entry point in every venv VIP is
        # installed into, and ``load_config`` returns defaults rather than
        # bailing when there is no vip.toml -- so without the gate, a lone
        # http_proxy would make an unrelated project's pytest run announce
        # egress behavior for a run that makes no egress at all.
        build_proxy_map(vip_cfg.proxy)

    _configure_auth(config, vip_cfg)


def pytest_configure_node(node) -> None:
    """Xdist controller hook: share interactive-auth credentials with workers."""
    # Forward the auth mode even when no browser session was established (e.g.
    # only Package Manager configured, so the flow was skipped). Workers don't
    # re-run the controller-only auth branch, so without this their auth_mode
    # fixture would resolve to "none" while a non-xdist run reports the mode.
    mode = node.config.stash.get(_auth_mode_key, "")
    if mode:
        node.workerinput["vip_auth_mode"] = mode
    auth = node.config.stash.get(_auth_session_key, None)
    if auth is not None:
        node.workerinput["vip_interactive_auth"] = True
        node.workerinput["vip_api_key"] = auth.api_key or ""
        node.workerinput["vip_storage_state"] = str(auth.storage_state_path)
        node.workerinput["vip_key_name"] = auth.key_name
        node.workerinput["vip_connect_url"] = auth._connect_url
        node.workerinput["vip_workbench_url"] = auth._workbench_url
        node.workerinput["vip_workbench_auth_error"] = auth.workbench_auth_error or ""


def pytest_sessionstart(session: pytest.Session) -> None:
    """Add extension directories to sys.path so their conftest / modules
    are importable, register them for collection, recolor progress indicators
    per-line, and shorten node paths.
    """
    # Wrap the terminal reporter here rather than in pytest_configure: the
    # builtin terminal plugin registers "terminalreporter" in its own
    # pytest_configure, which pluggy may call after ours.  By sessionstart the
    # reporter is guaranteed to exist.
    _install_progress_recolor(session.config)
    _install_location_shortener(session.config)
    session.config.stash[_session_start_key] = time.monotonic()

    ext_dirs = session.config.stash.get(_ext_dirs_key, [])
    for d in ext_dirs:
        p = Path(d).resolve()
        if p.is_dir():
            str_p = str(p)
            if str_p not in sys.path:
                sys.path.insert(0, str_p)
            # Tell pytest to collect from this directory as well.
            session.config.args.append(str_p)
