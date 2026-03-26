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
