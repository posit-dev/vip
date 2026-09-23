"""VIP command-line tools for credential management and verification.

One module per subcommand; ``app`` builds the parser and holds ``main()``.
The package namespace re-exports every name imported from ``vip.cli``.
Patch a helper on the submodule that calls it, not here: a re-export does
not change the global the submodule looks up.
"""

from vip.cli.app import _reorder_help_args, main
from vip.cli.auth import mint_connect_key
from vip.cli.cleanup import _cleanup_workbench_sessions, run_cleanup
from vip.cli.install import run_install, run_uninstall
from vip.cli.report import (
    _REPORT_TEMPLATE_FILES,
    _ensure_report_templates,
    _has_all_report_templates,
    run_report,
)
from vip.cli.scaffold import run_scaffold
from vip.cli.status import _collect_status, run_status
from vip.cli.verify import (
    _OPT_IN_CATEGORIES,
    DEFAULT_TEST_TIMEOUT_SECONDS,
    _default_marker_expr,
    _extra_keep_from_args,
    _generate_temp_config,
    _normalize_categories,
    run_verify,
)
from vip.cli.version import run_version

__all__ = [
    "DEFAULT_TEST_TIMEOUT_SECONDS",
    "_OPT_IN_CATEGORIES",
    "_REPORT_TEMPLATE_FILES",
    "_cleanup_workbench_sessions",
    "_collect_status",
    "_default_marker_expr",
    "_ensure_report_templates",
    "_extra_keep_from_args",
    "_generate_temp_config",
    "_has_all_report_templates",
    "_normalize_categories",
    "_reorder_help_args",
    "main",
    "mint_connect_key",
    "run_cleanup",
    "run_install",
    "run_report",
    "run_scaffold",
    "run_status",
    "run_uninstall",
    "run_verify",
    "run_version",
]
