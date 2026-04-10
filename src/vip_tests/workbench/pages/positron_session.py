"""Positron session selectors.

Mirrors: rstudio-pro/e2e/pages/positron_session.page.ts
"""

from vip_tests.workbench.pages.vscode_session import _EXTENSION_ID_RE


class PositronSession:
    """Selectors for the Positron IDE.

    Positron is based on VS Code, so many selectors are similar.
    """

    # Core UI elements (VS Code based)
    WORKBENCH = ".monaco-workbench"
    STATUS_BAR = ".statusbar"
    ACTIVITY_BAR = ".activitybar"
    SIDEBAR = ".sidebar"

    # Positron-specific elements
    CONSOLE_PANEL = ".positron-console"
    VARIABLES_PANE = ".positron-variables"
    PLOTS_PANE = ".positron-plots"
    HELP_PANE = ".positron-help"

    # Data explorer
    DATA_EXPLORER = ".positron-data-explorer"

    # Extensions panel (same as VS Code)
    EXTENSIONS_SEARCH_INPUT = ".extensions-search-container input[type='text']"

    # Posit Workbench extension
    POSIT_EXTENSION_TAB_NAME = "Posit Workbench"
    POSIT_EXTENSION_HOME_BUTTON_NAME = "home Posit Workbench"

    @staticmethod
    def extension_list_item(extension_id: str) -> str:
        """Selector for an installed extension by its ID (e.g. 'quarto.quarto')."""
        if not _EXTENSION_ID_RE.match(extension_id):
            raise ValueError(f"Invalid extension ID (contains unsafe characters): {extension_id!r}")
        return f".extension-list-item[data-extension-id='{extension_id}']"
