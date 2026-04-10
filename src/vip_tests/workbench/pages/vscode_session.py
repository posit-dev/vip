"""VS Code session selectors.

Mirrors: rstudio-pro/e2e/pages/vscode_session.page.ts
"""

import re

_EXTENSION_ID_RE = re.compile(r"^[\w.-]+$")


class VSCodeSession:
    """Selectors for the VS Code IDE."""

    # Core UI elements
    WORKBENCH = ".monaco-workbench"
    STATUS_BAR = ".statusbar"
    ACTIVITY_BAR = ".activitybar"
    SIDEBAR = ".sidebar"
    EDITOR_AREA = ".editor-container"

    # Title bar
    TITLE_BAR = ".titlebar"

    # Terminal
    TERMINAL_PANEL = ".terminal"
    TERMINAL_INPUT = ".xterm-helper-textarea"

    # Extensions panel
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
