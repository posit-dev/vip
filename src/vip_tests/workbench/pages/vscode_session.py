"""VS Code session selectors.

Mirrors: rstudio-pro/e2e/pages/vscode_session.page.ts
"""


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
    EXTENSIONS_SEARCH_INPUT = ".extensions-viewlet .inputarea"

    # Posit Workbench extension
    POSIT_EXTENSION_TAB_NAME = "Posit Workbench"
    POSIT_EXTENSION_HOME_BUTTON_NAME = "home Posit Workbench"

    @staticmethod
    def extension_list_item(extension_id: str) -> str:
        """Selector for an installed extension by its ID (e.g. 'quarto.quarto')."""
        return f".extension-list-item[data-extension-id='{extension_id}']"
